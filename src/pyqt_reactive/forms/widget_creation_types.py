"""
React-quality UI framework for Python - Type-safe widget creation.

Uses ABC + dataclass with proper metaclass resolution.
All components MUST inherit from ParameterFormManager and implement the interface.

This is the Python equivalent of React's component interface:
- State management (parameters, nested_managers, widgets)
- Lifecycle hooks (_apply_initial_enabled_styling)
- Reactive updates (update_parameter, reset_parameter) - routed through FieldChangeDispatcher
- Component tree traversal (_apply_to_nested_managers)
"""

from abc import ABC, abstractmethod, ABCMeta
from enum import Enum
from typing import TypedDict, Callable, Optional, Any, Dict, Type
from dataclasses import dataclass, replace as dataclass_replace

# Import ParameterInfo ABC from shared UI module
from .parameter_info_types import ParameterInfoBase as ParameterInfo


class DisplayInfo(TypedDict, total=False):
    """Type-safe display information for a parameter."""
    field_label: str
    checkbox_label: str
    description: str


class FieldIds(TypedDict, total=False):
    """Type-safe field ID mapping."""
    widget_id: str
    optional_checkbox_id: str


class LayoutKind(Enum):
    """Nominal layout strategy for widget containers."""
    HORIZONTAL_ROW = "horizontal_row"
    VERTICAL_BOX = "vertical_box"
    PRECONFIGURED_GROUPBOX = "preconfigured_groupbox"
    GROUPBOX_WITH_HELP = "groupbox_with_help"


@dataclass(frozen=True)
class OptionalTitleComponents:
    """Widgets that make up an optional nested dataclass title row."""
    title_widget: Any
    checkbox: Any
    title_label: Any
    help_btn: Any
    reset_all_button: Optional[Any]


@dataclass(frozen=True)
class WidgetBuildContext:
    """Shared context for one parameter widget build."""
    manager: 'ParameterFormManager'
    param_info: ParameterInfo
    display_info: DisplayInfo
    field_ids: FieldIds
    current_value: Any
    unwrapped_type: Optional[Type]
    container: Optional[Any] = None
    layout: Optional[Any] = None
    layout_config: Optional[Any] = None
    qwidget_type: Optional[type] = None
    groupbox_with_help_type: Optional[type] = None
    color_scheme_type: Optional[type] = None

    def with_layout(self, layout: Any) -> 'WidgetBuildContext':
        return dataclass_replace(self, layout=layout)

    def with_container(self, container: Any) -> 'WidgetBuildContext':
        return dataclass_replace(self, container=container)


from PyQt6.QtWidgets import QWidget


class _CombinedMeta(ABCMeta, type(QWidget)):
    """Combined metaclass for ABC + PyQt6 QWidget."""


class ParameterFormManager(ABC, metaclass=_CombinedMeta):
    """
    React-quality reactive form manager interface.

    All components MUST inherit from this ABC and implement all abstract methods.
    Uses dataclass for clean state declaration.

    Semantics (React equivalents):
    - State: parameters, nested_managers, widgets (like React state)
    - Lifecycle: _apply_initial_enabled_styling (like useEffect)
    - Reactive updates: update_parameter/reset_parameter routed through FieldChangeDispatcher
    - Component tree: _apply_to_nested_managers (like recursive component traversal)
    """

    # ==================== STATE ====================
    # These are like React component state
    read_only: bool
    parameters: Dict[str, Any]
    nested_managers: Dict[str, Any]
    widgets: Dict[str, Any]
    reset_buttons: Dict[str, Any]
    color_scheme: Any
    config: Any
    service: Any
    _widget_ops: Any
    _on_build_complete_callbacks: list

    # ==================== LIFECYCLE HOOKS ====================
    # These are like React useEffect hooks
    # DELETED: _emit_parameter_change - replaced by FieldChangeDispatcher

    # ==================== STATE MUTATIONS ====================
    # These are like React state setters

    @abstractmethod
    def update_parameter(self, param_name: str, value: Any) -> None:
        """
        Update parameter in data model.

        Equivalent to: setState(name, value)
        """
        pass

    @abstractmethod
    def reset_parameter(self, param_name: str) -> None:
        """
        Reset parameter to default value.

        Equivalent to: setState(name, defaultValue)
        """
        pass

    # ==================== WIDGET CREATION ====================
    # These are like React component rendering

    @abstractmethod
    def _create_nested_form_inline(self, param_name: str, unwrapped_type: Type,
                                   current_value: Any) -> Any:
        """
        Create nested form manager inline.

        Equivalent to: render(<NestedForm ... />)
        """
        pass

    # ==================== COMPONENT TREE TRAVERSAL ====================
    # These are like React's recursive component tree operations

    @abstractmethod
    def _apply_to_nested_managers(self, callback: Callable[[str, Any], None]) -> None:
        """
        Apply operation to all nested managers recursively.

        Equivalent to: traverseComponentTree(callback)
        """
        pass


# Type aliases for handler signatures
WidgetOperationHandler = Callable[[WidgetBuildContext], Any]

OptionalTitleHandler = Callable[[WidgetBuildContext], OptionalTitleComponents]

CheckboxLogicHandler = Callable[
    ['ParameterFormManager', 'ParameterInfo', Any, Any, Any, Any, Any, Type],
    None
]


@dataclass
class WidgetCreationConfig:
    """Type-safe configuration for a widget creation type."""
    layout_type: LayoutKind
    is_nested: bool
    create_container: WidgetOperationHandler
    setup_layout: Optional[WidgetOperationHandler]
    create_main_widget: WidgetOperationHandler
    needs_label: bool
    needs_reset_button: bool
    needs_unwrap_type: bool
    is_optional: bool = False
    needs_checkbox: bool = False
    is_enableable: bool = False
    create_title_widget: Optional[OptionalTitleHandler] = None
    connect_checkbox_logic: Optional[CheckboxLogicHandler] = None
