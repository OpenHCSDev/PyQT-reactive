"""
Typed helpers for function-field navigation payloads.

This module owns the ``func`` field-path conventions used for cross-window
navigation so callers do not duplicate string parsing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

FUNCTION_FIELD_ROOT = "func"
FUNCTION_TOKEN_FIELD_PREFIX = "func.token:"
FUNCTION_TARGET_DELIMITER = "|"


@dataclass(frozen=True)
class FunctionFieldTarget:
    """Parsed function navigation target."""

    token: Optional[str]
    index: Optional[int]
    base_field_path: str


def is_function_field_path(field_path: str | None) -> bool:
    """Return True when the field path targets function-pattern UI."""
    return isinstance(field_path, str) and field_path.startswith(FUNCTION_FIELD_ROOT)


def build_function_token_field_path(
    token: str,
    fallback_base_field_path: str = FUNCTION_FIELD_ROOT,
) -> str:
    """Build a token-scoped function field path payload."""
    normalized_token = token.strip()
    if not normalized_token:
        raise ValueError("Function token must be non-empty.")
    normalized_base = fallback_base_field_path.strip() or FUNCTION_FIELD_ROOT
    return (
        f"{FUNCTION_TOKEN_FIELD_PREFIX}{normalized_token}"
        f"{FUNCTION_TARGET_DELIMITER}{normalized_base}"
    )


def parse_function_field_target(field_path: str) -> FunctionFieldTarget:
    """Parse function field path into token/index/base components."""
    normalized = field_path.strip()
    token: Optional[str] = None

    if normalized.startswith(FUNCTION_TOKEN_FIELD_PREFIX):
        payload = normalized[len(FUNCTION_TOKEN_FIELD_PREFIX) :]
        if FUNCTION_TARGET_DELIMITER in payload:
            token_part, remainder = payload.split(FUNCTION_TARGET_DELIMITER, 1)
            token = token_part.strip() or None
            normalized = remainder.strip() or FUNCTION_FIELD_ROOT
        else:
            token = payload.strip() or None
            normalized = FUNCTION_FIELD_ROOT

    index: Optional[int] = None
    rest = normalized
    if rest.startswith(FUNCTION_FIELD_ROOT):
        rest = rest[len(FUNCTION_FIELD_ROOT) :]

    if rest.startswith("["):
        close = rest.find("]")
        if close > 1:
            digits = rest[1:close]
            if digits.isdigit():
                index = int(digits)
    elif rest.startswith("."):
        parts = rest[1:].split(".", 1)
        if parts and parts[0].isdigit():
            index = int(parts[0])

    return FunctionFieldTarget(
        token=token,
        index=index,
        base_field_path=normalized,
    )
