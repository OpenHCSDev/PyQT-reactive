"""
Shared widget utilities and components.
"""

from .scrollable_form_mixin import ScrollableFormMixin
from .tabbed_form_widget import TabbedFormWidget, TabConfig, TabbedFormConfig
from .base_form_dialog import BaseManagedWindow, BaseFormDialog

__all__ = [
    "ScrollableFormMixin",
    "TabbedFormWidget",
    "TabConfig",
    "TabbedFormConfig",
    "BaseManagedWindow",
    "BaseFormDialog",
]

