"""
Generic preview formatting helpers.

These utilities are framework-agnostic and avoid OpenHCS-specific imports.
"""

from types import FunctionType, MethodType
from typing import Any, Optional, Callable


def check_enabled_field(config: Any, resolve_attr: Optional[Callable] = None) -> bool:
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
    if isinstance(value, (FunctionType, MethodType)):
        return value.__name__
    if callable(value) and not isinstance(value, type):
        return type(value).__name__
    return str(value)
