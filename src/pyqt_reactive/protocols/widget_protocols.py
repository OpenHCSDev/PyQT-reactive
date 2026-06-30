"""
Widget ABC contracts for OpenHCS UI frameworks.

Defines explicit contracts that all widgets must implement, eliminating duck typing
in favor of fail-loud inheritance-based architecture.

Design Philosophy:
- Explicit inheritance over duck typing
- Fail-loud over fail-silent
- Discoverable over scattered
- Multiple inheritance for composable capabilities

Inspired by OpenHCS patterns:
- StorageBackendMeta: Metaclass auto-registration
- MemoryTypeConverter: ABC contracts with adapters
- LibraryRegistryBase: Centralized operations
"""

from abc import ABC, abstractmethod
from typing import Any, Callable


class ValueGettable(ABC):
    """
    ABC for widgets that can return a value.
    
    All input widgets must implement this to participate in form value extraction.
    """
    
    @abstractmethod
    def get_value(self) -> Any:
        """
        Get the current value from the widget.
        
        Returns:
            The widget's current value. None if no value set.
        """
        pass


class ValueSettable(ABC):
    """
    ABC for widgets that can accept a value.
    
    All input widgets must implement this to participate in form value updates.
    """
    
    @abstractmethod
    def set_value(self, value: Any) -> None:
        """
        Set the widget's value.
        
        Args:
            value: The value to set. None clears the widget.
        """
        pass


class ResolvedValuePreviewSettable(ABC):
    """
    ABC for widgets that render inherited/resolved values separately from raw edits.

    Lazy dataclass container widgets may keep raw ``None`` child fields while
    previewing the resolved inherited dataclass. This contract lets form chrome
    refresh that preview without replacing the raw editable value.
    """

    @abstractmethod
    def set_resolved_value_preview(self, value: Any) -> None:
        """
        Set the resolved value used for display/preview only.

        Args:
            value: Resolved value for the same logical field.
        """
        pass


class ChildFieldChromeRefreshable(ABC):
    """
    ABC for compound widgets that render chrome for their own child fields.

    Inline dataclass widgets can own section labels/reset controls internally
    while still being edited as one form value. This contract lets the form
    manager refresh those child markers after ObjectState dirty/signature state
    changes without knowing widget-specific field names.
    """

    @abstractmethod
    def refresh_child_field_chrome(self) -> None:
        """Refresh dirty/signature/reset chrome for child fields."""
        pass


class ChildFieldNavigationTargetProvider(ABC):
    """
    ABC for compound widgets that expose concrete widgets for child fields.

    Inline dataclass widgets may render their own child sections internally
    instead of creating nested ParameterFormManager instances. This contract
    lets generic form navigation scroll to the concrete child section while
    keeping the widget-specific layout private to the inline editor.
    """

    @abstractmethod
    def child_field_navigation_target(self, field_name: str) -> Any | None:
        """
        Return the widget that visually represents a child field, if present.

        Args:
            field_name: Direct child field name inside the compound widget.
        """
        pass


class InlineDataclassGroupBoxChromeProvider(ABC):
    """
    ABC for inline dataclass value widgets that contribute container title chrome.

    Regular nested dataclasses can move child widgets such as enableable checkboxes
    into the groupbox title row. Inline dataclass widgets do not have a nested
    ParameterFormManager, so they expose the same chrome through this contract
    while the container remains generic.
    """

    @abstractmethod
    def configure_inline_dataclass_groupbox(self, groupbox: Any) -> None:
        """
        Attach any inline title chrome to the owning groupbox.

        Args:
            groupbox: The InlineDataclassGroupBox hosting this value widget.
        """
        pass


class PlaceholderCapable(ABC):
    """
    ABC for widgets that can display placeholder text.
    
    Placeholders show inherited/default values without setting actual values.
    """
    
    @abstractmethod
    def set_placeholder(self, text: str) -> None:
        """
        Set placeholder text for the widget.
        
        Args:
            text: Placeholder text to display (e.g., "Pipeline default: 42")
        """
        pass


class RangeConfigurable(ABC):
    """
    ABC for widgets that support numeric range configuration.
    
    Typically implemented by numeric input widgets (spinboxes, sliders).
    """
    
    @abstractmethod
    def configure_range(self, minimum: float, maximum: float) -> None:
        """
        Configure the valid range for numeric input.
        
        Args:
            minimum: Minimum allowed value
            maximum: Maximum allowed value
        """
        pass


class EnumSelectable(ABC):
    """
    ABC for widgets that can select from enum values.
    
    Typically implemented by dropdowns and radio button groups.
    """
    
    @abstractmethod
    def set_enum_options(self, enum_type: type) -> None:
        """
        Configure widget with enum options.
        
        Args:
            enum_type: The Enum class to populate options from
        """
        pass
    
    @abstractmethod
    def get_selected_enum(self) -> Any:
        """
        Get the currently selected enum value.
        
        Returns:
            The selected enum member, or None if no selection
        """
        pass


class ChangeSignalEmitter(ABC):
    """
    ABC for widgets that emit change signals.
    
    Provides explicit contract for signal connection, eliminating duck typing
    of signal names (textChanged vs valueChanged vs currentIndexChanged).
    """
    
    @abstractmethod
    def connect_change_signal(self, callback: Callable[[Any], None]) -> None:
        """
        Connect callback to widget's change signal.
        
        The callback will be invoked whenever the widget's value changes,
        receiving the new value as its argument.
        
        Args:
            callback: Function to call when widget value changes.
                     Signature: callback(new_value: Any) -> None
        """
        pass
    
    @abstractmethod
    def disconnect_change_signal(self, callback: Callable[[Any], None]) -> None:
        """
        Disconnect callback from widget's change signal.
        
        Args:
            callback: The callback function to disconnect
        """
        pass
