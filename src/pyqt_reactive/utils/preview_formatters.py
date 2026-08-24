"""Generic preview formatting helpers."""

from dataclasses import dataclass
from types import FunctionType, MethodType
from typing import cast

from objectstate import ParameterOwner


@dataclass(frozen=True, slots=True)
class PreviewLabelResolution:
    """Preview label together with the config declaration that owns it."""

    owner: type
    label: str


@dataclass(frozen=True, slots=True)
class PreviewFieldFormatRequest:
    """One resolved value together with its ObjectState-recorded declaration."""

    field_path: str
    value: object
    field_owner: ParameterOwner

    @property
    def field_name(self) -> str:
        """Return the leaf field name declared by ``field_owner``."""
        return self.field_path.rsplit(".", 1)[-1]


@dataclass(frozen=True, slots=True)
class PreviewFieldAbbreviationResolution:
    """Field abbreviation together with the declaration that owns it."""

    owner: type
    abbreviation: str


def canonical_declaration_mro(declaration_type: type) -> tuple[type, ...]:
    """Return the semantic declaration MRO, excluding generated lazy wrappers."""
    from objectstate.lazy_factory import get_base_type_for_lazy

    canonical_type = get_base_type_for_lazy(declaration_type) or declaration_type
    return canonical_type.__mro__


def resolve_preview_label(config: object) -> PreviewLabelResolution | None:
    """Resolve preview metadata from the canonical config declaration MRO."""
    from objectstate.lazy_factory import PREVIEW_LABEL_REGISTRY

    for candidate in canonical_declaration_mro(type(config)):
        label = PREVIEW_LABEL_REGISTRY.get(candidate)
        if label is not None:
            return PreviewLabelResolution(owner=candidate, label=label)
    return None


def resolve_field_abbreviation(
    declaration: ParameterOwner,
    field_name: str,
) -> PreviewFieldAbbreviationResolution | None:
    """Resolve a field abbreviation only from its canonical declaration MRO."""
    from objectstate.lazy_factory import FIELD_ABBREVIATIONS_REGISTRY

    if not isinstance(declaration, type):
        return None

    for candidate in canonical_declaration_mro(declaration):
        abbreviation = FIELD_ABBREVIATIONS_REGISTRY.get(candidate, {}).get(field_name)
        if abbreviation is not None:
            return PreviewFieldAbbreviationResolution(
                owner=candidate,
                abbreviation=abbreviation,
            )
    return None


def check_enabled_field(config: object) -> bool:
    """Return the nominal ``Enableable`` state of a config declaration."""
    from python_introspect import Enableable

    if not issubclass(type(config), Enableable):
        return True
    return cast(Enableable, config).enabled


def format_preview_value(value: object) -> str | None:
    """Format any value for preview display. Simple type-based, no field knowledge needed.

    Args:
        value: Any value to format

    Returns:
        Formatted string or None if value should be skipped
    """
    from enum import Enum

    if value is None:
        return None
    if isinstance(value, Enum):
        if value.value is None:
            return None  # Skip null enums like GroupBy.NONE
        return value.name
    if isinstance(value, list):
        if not value:
            return None
        # List of enums: show values joined
        if isinstance(value[0], Enum):
            return ",".join(v.value for v in value)
        # Other lists: show count
        return f"[{len(value)}]"
    if isinstance(value, (FunctionType, MethodType)):
        return value.__name__
    if callable(value) and not isinstance(value, type):
        return type(value).__name__
    return str(value)
