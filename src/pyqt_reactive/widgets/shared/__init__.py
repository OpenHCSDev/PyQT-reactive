"""
Shared widget utilities and components.
"""

from .scrollable_form_mixin import ScrollableFormMixin
from .tabbed_form_widget import TabbedFormWidget, TabConfig, TabbedFormConfig
from .base_form_dialog import BaseManagedWindow, BaseFormDialog
from .tear_off_tab_widget import TearOffTabWidget, FloatingTabWindow, TearOffTabBar
from .tear_off_registry import TearOffRegistry
from .responsive_layout_widgets import (
    ResponsiveTwoRowWidget, ResponsiveParameterRow,
    set_wrapping_enabled as set_row_wrapping_enabled,
    is_wrapping_enabled as is_row_wrapping_enabled
)
from .responsive_groupbox_title import (
    ResponsiveGroupBoxTitle,
    set_wrapping_enabled as set_groupbox_wrapping_enabled,
    is_wrapping_enabled as is_groupbox_wrapping_enabled
)

# Unified wrapping toggle
def set_responsive_wrapping_enabled(enabled: bool):
    """Globally enable or disable all responsive wrapping (rows and groupbox titles)."""
    set_row_wrapping_enabled(enabled)
    set_groupbox_wrapping_enabled(enabled)

def is_responsive_wrapping_enabled() -> bool:
    """Check if responsive wrapping is globally enabled."""
    return is_row_wrapping_enabled() and is_groupbox_wrapping_enabled()

__all__ = [
    "ScrollableFormMixin",
    "TabbedFormWidget",
    "TabConfig",
    "TabbedFormConfig",
    "BaseManagedWindow",
    "BaseFormDialog",
    "TearOffTabWidget",
    "FloatingTabWindow",
    "TearOffTabBar",
    "TearOffRegistry",
    "ResponsiveTwoRowWidget",
    "ResponsiveParameterRow",
    "ResponsiveGroupBoxTitle",
    "set_responsive_wrapping_enabled",
    "is_responsive_wrapping_enabled",
]

