"""
Generic preview formatting helpers.

These utilities are framework-agnostic and avoid OpenHCS-specific imports.
"""

from typing import Any, Optional, Callable


def check_enabled_field(config: Any, resolve_attr: Optional[Callable] = None) -> bool:
    """Check if a config object is enabled via an 'enabled' field.

    Args:
        config: Config object to check
        resolve_attr: Optional function to resolve lazy config attributes

    Returns:
        True if config is enabled (or has no enabled field), False if disabled
    """
    import dataclasses

    # Check if config has 'enabled' field
    if not dataclasses.is_dataclass(config):
        return True

    has_enabled = "enabled" in {f.name for f in dataclasses.fields(config)}
    if not has_enabled:
        return True

    # Resolve enabled field - we know it exists
    if resolve_attr:
        enabled = resolve_attr(None, config, "enabled", None)
    else:
        enabled = object.__getattribute__(config, "enabled")

    return bool(enabled)


def format_preview_value(value: Any) -> Optional[str]:
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
    if callable(value) and not isinstance(value, type):
        return getattr(value, "__name__", str(value))
    return str(value)
