"""
Helpers for generating stable scope tokens for ObjectState hierarchy nodes.

Used to avoid cross-window collisions when multiple child editors share the
same scope prefix (e.g., steps, nested functions).
"""

from __future__ import annotations

from abc import ABC
import logging
from typing import Iterable, Optional, Sequence, Set

logger = logging.getLogger(__name__)


class ScopeTokenTarget(ABC):
    """Nominal role for objects that can participate in scope-token identity."""


class ScopeTokenObjectStore:
    """Persist scope tokens without exposing attribute probing to callers."""

    @classmethod
    def read(cls, obj: ScopeTokenTarget, attr_name: str) -> Optional[str]:
        attributes = cls._instance_attributes(obj)
        if attributes is not None and attr_name in attributes:
            token = attributes[attr_name]
            if isinstance(token, str) and token:
                return token
        return None

    @classmethod
    def write(cls, obj: ScopeTokenTarget, attr_name: str, token: str) -> None:
        attributes = cls._instance_attributes(obj)
        attributes[attr_name] = token

    @staticmethod
    def _instance_attributes(obj: ScopeTokenTarget):
        try:
            return vars(obj)
        except TypeError as exc:
            raise TypeError(
                "Scope-token targets must expose an instance attribute mapping."
            ) from exc


class ScopeTokenGenerator:
    """Generate unique, human-readable scope tokens with an optional attribute store.

    - If attr_name is provided and the target object exposes an instance mapping,
      tokens are persisted there (e.g., FunctionStep._scope_token).
    - Tracks seen tokens to avoid collisions when objects already carry tokens
      (e.g., after deserialization).
    """

    def __init__(self, prefix: str, attr_name: Optional[str] = None):
        self.prefix = prefix
        self.attr_name = attr_name
        self._counter: int = 0
        self._used_tokens: Set[str] = set()

    # ---------- Seeding ----------
    def seed_from_tokens(self, tokens: Iterable[str] | None) -> None:
        """Prime the generator with existing tokens (keeps counter ahead of them)."""
        if tokens is None:
            return
        for token in tokens:
            if not token:
                continue
            self._register_existing(token)

    def seed_from_objects(
        self,
        objects: Iterable[ScopeTokenTarget] | None,
    ) -> None:
        """Seed from objects that may already carry tokens on attr_name."""
        if not self.attr_name:
            return
        if objects is None:
            return
        for obj in objects:
            token = self._get_existing(obj)
            if token:
                self._register_existing(token)

    # ---------- Public API ----------
    def ensure(self, obj: Optional[ScopeTokenTarget] = None) -> str:
        """Return an existing token on obj or generate a new one."""
        existing = self._get_existing(obj)
        if existing:
            self._register_existing(existing)
            return existing

        token = self._generate_new()
        self._attach(obj, token)
        return token

    def transfer(self, source: ScopeTokenTarget, target: ScopeTokenTarget) -> str:
        """Copy source token to target (or generate a new one for target)."""
        token = self._get_existing(source)
        if not token:
            token = self.ensure(target)
            return token

        self._register_existing(token)
        self._attach(target, token)
        return token

    def normalize(self, objects: Iterable[ScopeTokenTarget] | None) -> None:
        """Ensure every object in a list has a token."""
        if objects is None:
            return
        for obj in objects:
            self.ensure(obj)

    # ---------- Internals ----------
    def _get_existing(self, obj: Optional[ScopeTokenTarget]) -> Optional[str]:
        if obj is None or not self.attr_name:
            return None
        token = self.existing_token(obj, self.attr_name)
        return token

    @staticmethod
    def existing_token(obj: ScopeTokenTarget, attr_name: str) -> Optional[str]:
        """Return an existing token from the configured storage attribute."""
        return ScopeTokenObjectStore.read(obj, attr_name)

    def _attach(self, obj: Optional[ScopeTokenTarget], token: str) -> None:
        if obj is None or not self.attr_name:
            return
        ScopeTokenObjectStore.write(obj, self.attr_name, token)

    def _register_existing(self, token: str) -> None:
        if token in self._used_tokens:
            return
        self._used_tokens.add(token)
        self._bump_counter(token)

    def _bump_counter(self, token: str) -> None:
        prefix = f"{self.prefix}_"
        if token.startswith(prefix):
            suffix = token[len(prefix) :]
            if suffix.isdigit():
                self._counter = max(self._counter, int(suffix) + 1)

    def _generate_new(self) -> str:
        token = f"{self.prefix}_{self._counter}"
        while token in self._used_tokens:
            self._counter += 1
            token = f"{self.prefix}_{self._counter}"
        self._used_tokens.add(token)
        self._counter += 1
        return token


class ScopeTokenService:
    """Registry of ScopeTokenGenerators keyed by (parent_scope, prefix).

    Token assigned on creation, stable across reordering.
    Prefix derived from object type for readability.

    Usage:
        ScopeTokenService.build_scope_id(plate_path, step)   # → "plate::step_0"
        ScopeTokenService.build_scope_id(step_scope, func)   # → "plate::step_0::func_0"
    """
    _generators: dict[tuple[str, str], ScopeTokenGenerator] = {}

    @classmethod
    def _get_prefix(cls, obj: ScopeTokenTarget) -> str:
        """Derive prefix from object type (lowercase)."""
        return type(obj).__name__.lower()

    @classmethod
    def _normalize_scope(cls, scope) -> str:
        """Normalize scope to string. Enforces the invariant: scope keys are always strings."""
        if scope is None:
            return ""
        return str(scope)

    @classmethod
    def get_generator(cls, parent_scope, prefix: str) -> ScopeTokenGenerator:
        parent_scope = cls._normalize_scope(parent_scope)
        key = (parent_scope, prefix)
        if key not in cls._generators:
            cls._generators[key] = ScopeTokenGenerator(prefix, '_scope_token')
            logger.debug(f"🔑 ScopeTokenService: Created generator for parent_scope={parent_scope}, prefix={prefix}")
        return cls._generators[key]

    @classmethod
    def ensure_token(cls, parent_scope, obj: ScopeTokenTarget) -> str:
        parent_scope = cls._normalize_scope(parent_scope)
        prefix = cls._get_prefix(obj)
        return cls.get_generator(parent_scope, prefix).ensure(obj)

    @classmethod
    def transfer_token(
        cls,
        parent_scope,
        source: ScopeTokenTarget,
        target: ScopeTokenTarget,
    ) -> str:
        """Transfer source object's scope token to a replacement target."""
        parent_scope = cls._normalize_scope(parent_scope)
        prefix = cls._get_prefix(source)
        return cls.get_generator(parent_scope, prefix).transfer(source, target)

    @classmethod
    def adopt_token(
        cls,
        parent_scope,
        obj: ScopeTokenTarget,
        token: str,
    ) -> str:
        """Assign a known scope token to an object through the token authority."""
        parent_scope = cls._normalize_scope(parent_scope)
        prefix = cls._get_prefix(obj)
        generator = cls.get_generator(parent_scope, prefix)
        generator.seed_from_tokens((token,))
        if generator.attr_name is None:
            return token
        ScopeTokenObjectStore.write(obj, generator.attr_name, token)
        return token

    @classmethod
    def object_token(cls, obj: ScopeTokenTarget) -> str | None:
        """Return an object's existing scope token without creating one."""
        return ScopeTokenGenerator.existing_token(obj, "_scope_token")

    @classmethod
    def same_object_token(
        cls,
        left: ScopeTokenTarget,
        right: ScopeTokenTarget,
    ) -> bool:
        """Return whether two objects carry the same existing scope token."""
        left_token = cls.object_token(left)
        if left_token is None:
            return False
        return left_token == cls.object_token(right)

    # PERFORMANCE: Cache scope_id strings per (parent_scope, object_id)
    _scope_id_cache: dict[tuple[str, int], str] = {}

    @classmethod
    def build_scope_id(cls, parent_scope, obj: ScopeTokenTarget) -> str:
        parent_scope = cls._normalize_scope(parent_scope)
        # PERFORMANCE: Check cache first
        cache_key = (parent_scope, id(obj))
        if cache_key in cls._scope_id_cache:
            return cls._scope_id_cache[cache_key]

        token = cls.ensure_token(parent_scope, obj)
        result = f"{parent_scope}::{token}"
        cls._scope_id_cache[cache_key] = result
        logger.debug(f"🔑 ScopeTokenService.build_scope_id: {result} for {type(obj).__name__}")
        return result

    @classmethod
    def seed_from_objects(
        cls,
        parent_scope,
        objects: Sequence[ScopeTokenTarget],
    ) -> None:
        """Seed generators from existing objects (preserves their tokens)."""
        if not objects:
            return
        parent_scope = cls._normalize_scope(parent_scope)
        # Group by type prefix
        by_prefix: dict[str, list[ScopeTokenTarget]] = {}
        for obj in objects:
            prefix = cls._get_prefix(obj)
            if prefix not in by_prefix:
                by_prefix[prefix] = []
            by_prefix[prefix].append(obj)
        # Seed each generator
        for prefix, objs in by_prefix.items():
            cls.get_generator(parent_scope, prefix).seed_from_objects(objs)

    @classmethod
    def clear_scope(cls, parent_scope) -> None:
        """Clear all generators for a parent scope (and nested children)."""
        parent_scope = cls._normalize_scope(parent_scope)
        keys_to_remove = [k for k in cls._generators if k[0].startswith(parent_scope)]
        for key in keys_to_remove:
            del cls._generators[key]

        # PERFORMANCE: Also clear scope_id cache for this scope
        cache_keys_to_remove = [k for k in cls._scope_id_cache if k[0].startswith(parent_scope)]
        for key in cache_keys_to_remove:
            del cls._scope_id_cache[key]

        if keys_to_remove:
            logger.debug(f"🔑 ScopeTokenService: Cleared {len(keys_to_remove)} generators for {parent_scope}")
