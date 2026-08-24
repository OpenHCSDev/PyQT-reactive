"""Generic preview formatting helpers."""

from collections.abc import Callable
from dataclasses import dataclass
from types import FunctionType, MethodType


@dataclass(frozen=True, slots=True)
class PreviewLabelResolution:
    """Preview label together with the config declaration that owns it."""

    owner: type
    label: str


def resolve_preview_label(config: object) -> PreviewLabelResolution | None:
    """Resolve preview metadata from the canonical config declaration MRO."""
    from objectstate.lazy_factory import (
        PREVIEW_LABEL_REGISTRY,
        get_base_type_for_lazy,
    )

    config_type = type(config)
    declaration_type = get_base_type_for_lazy(config_type) or config_type
    for candidate in declaration_type.__mro__:
        label = PREVIEW_LABEL_REGISTRY.get(candidate)
        if label is not None:
            return PreviewLabelResolution(owner=candidate, label=label)
    return None


def check_enabled_field(
    config: object,
    resolve_attr: Callable[..., object] | None = None,
) -> bool:
    """Check if a config object is enabled via an 'enabled' field.

    Args:
        config: Config object to check
        resolve_attr: Optional function to resolve lazy config attributes

    Returns:
        True if config is enabled (or has no enabled field), False if disabled
    """
    from python_introspect import Enableable, is_enableable

    if not is_enableable(config):
        return True

    # Resolve enabled field - we know it exists
    enabled_field = Enableable.require_parameter_name()
    if resolve_attr:
        enabled = resolve_attr(None, config, enabled_field, None)
    else:
        enabled = object.__getattribute__(config, enabled_field)

    return bool(enabled)


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
