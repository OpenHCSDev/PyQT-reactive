"""
Form generation and management.

ParameterFormManager and supporting infrastructure for automatic
form generation from dataclasses and function signatures.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .parameter_form_manager import ParameterFormManager, FormManagerConfig
    from .widget_creation_types import WidgetCreationConfig
    from .widget_factory import WidgetFactory
    from .widget_registry import (
        WidgetMeta,
        WIDGET_IMPLEMENTATIONS,
        WIDGET_CAPABILITIES,
        get_widget_class,
        get_widget_capabilities,
        list_widgets_with_capability,
    )
    from .widget_operations import WidgetOperations
    from .form_init_service import FormBuildOrchestrator
    from .parameter_info_types import ParameterInfoBase

_EXPORTS = {
    "ParameterFormManager": ("pyqt_reactive.forms.parameter_form_manager", "ParameterFormManager"),
    "FormManagerConfig": ("pyqt_reactive.forms.parameter_form_manager", "FormManagerConfig"),
    "ParameterFormManagerBase": ("pyqt_reactive.forms.parameter_form_base", "ParameterFormManagerBase"),
    "ParameterFormService": ("pyqt_reactive.forms.parameter_form_service", "ParameterFormService"),
    "ParameterTypeUtils": ("pyqt_reactive.forms.parameter_type_utils", "ParameterTypeUtils"),
    "WidgetCreationConfig": ("pyqt_reactive.forms.widget_creation_types", "WidgetCreationConfig"),
    "WidgetFactory": ("pyqt_reactive.forms.widget_factory", "WidgetFactory"),
    "WidgetMeta": ("pyqt_reactive.forms.widget_registry", "WidgetMeta"),
    "WIDGET_IMPLEMENTATIONS": ("pyqt_reactive.forms.widget_registry", "WIDGET_IMPLEMENTATIONS"),
    "WIDGET_CAPABILITIES": ("pyqt_reactive.forms.widget_registry", "WIDGET_CAPABILITIES"),
    "get_widget_class": ("pyqt_reactive.forms.widget_registry", "get_widget_class"),
    "get_widget_capabilities": ("pyqt_reactive.forms.widget_registry", "get_widget_capabilities"),
    "list_widgets_with_capability": ("pyqt_reactive.forms.widget_registry", "list_widgets_with_capability"),
    "WidgetOperations": ("pyqt_reactive.forms.widget_operations", "WidgetOperations"),
    "FormBuildOrchestrator": ("pyqt_reactive.forms.form_init_service", "FormBuildOrchestrator"),
    "ParameterInfoBase": ("pyqt_reactive.forms.parameter_info_types", "ParameterInfoBase"),
    "OptionalDataclassInfo": ("pyqt_reactive.forms.parameter_info_types", "OptionalDataclassInfo"),
    "DirectDataclassInfo": ("pyqt_reactive.forms.parameter_info_types", "DirectDataclassInfo"),
    "GenericInfo": ("pyqt_reactive.forms.parameter_info_types", "GenericInfo"),
    "ParameterInfo": ("pyqt_reactive.forms.parameter_info_types", "ParameterInfo"),
    "create_parameter_info": ("pyqt_reactive.forms.parameter_info_types", "create_parameter_info"),
}


def __getattr__(name: str):
    if name in _EXPORTS:
        module_name, attr = _EXPORTS[name]
        module = importlib.import_module(module_name)
        value = getattr(module, attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = list(_EXPORTS.keys())
