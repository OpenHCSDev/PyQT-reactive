from __future__ import annotations

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
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, ClassVar

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget
    from objectstate import (
        DottedFieldPath,
        ObjectStateSubfieldSemanticIndex,
        StructuralValuePath,
    )
    from pyqt_reactive.forms.inline_dataclass_context import (
        InlineDataclassChildFieldIdentity,
    )
    from pyqt_reactive.widgets.structural_table import StructuralFlashTarget


class WidgetCapability(str, Enum):
    """Nominal widget capability tags for generic service-level queries."""

    PLACEHOLDER_STATE = "placeholder_state"


class WidgetCapabilityTagged(ABC):
    """Base for widget contracts that advertise generic capability tags."""

    widget_capabilities: ClassVar[frozenset[WidgetCapability]] = frozenset()


def widget_capability_tags(widget_or_type: Any) -> frozenset[WidgetCapability]:
    """Return all capability tags declared by a widget class and its bases."""
    widget_type = widget_or_type if isinstance(widget_or_type, type) else type(widget_or_type)
    capabilities: set[WidgetCapability] = set()
    for cls in reversed(widget_type.__mro__):
        capabilities.update(getattr(cls, "widget_capabilities", ()))
    return frozenset(capabilities)


def widget_supports_capability(widget_or_type: Any, capability: WidgetCapability) -> bool:
    """Return whether a widget class declares a nominal capability tag."""
    return capability in widget_capability_tags(widget_or_type)


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


class RawResolvedValueSettable(ABC):
    """
    ABC for widgets that can atomically apply a raw value and resolved preview.

    Lazy dataclass widgets can avoid rendering a raw intermediate state when a
    form refresh already has both ObjectState values available.
    """

    @abstractmethod
    def set_raw_value_with_resolved_preview(
        self,
        raw_value: Any,
        resolved_value: Any,
    ) -> None:
        """
        Set the editable raw value and resolved display preview in one pass.

        Args:
            raw_value: Raw ObjectState value for editing.
            resolved_value: Resolved ObjectState value for inherited preview.
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
    def refresh_child_field_chrome(
        self,
        owner_field_paths: tuple["DottedFieldPath", ...] | None = None,
    ) -> None:
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
    def child_field_navigation_target(self, field_name: str) -> "QWidget | None":
        """
        Return the widget that visually represents a child field, if present.

        Args:
            field_name: Direct child field name inside the compound widget.
        """
        pass


class ChildFieldIdentityProvider(ABC):
    """ABC for compound widgets that expose nominal child ObjectState identity."""

    @abstractmethod
    def child_field_identity(
        self,
        field_name: str,
    ) -> "InlineDataclassChildFieldIdentity":
        """Return the nominal identity for one direct child field."""
        pass


class ChildFieldSemanticChromeRefreshable(ABC):
    """ABC for compound widgets that render semantic chrome for child leaves."""

    @abstractmethod
    def child_field_semantic_owner_paths(self) -> tuple["DottedFieldPath", ...]:
        """Return ObjectState owner paths for structural child semantics."""
        pass

    @abstractmethod
    def refresh_child_field_semantics(
        self,
        owner_field_path: "DottedFieldPath",
        semantic_index: "ObjectStateSubfieldSemanticIndex",
    ) -> None:
        """Refresh dirty/default/inherited chrome for an ObjectState owner field."""
        pass


class ChildSubfieldNavigationTargetProvider(ABC):
    """ABC for compound widgets that expose structural descendant targets."""

    @abstractmethod
    def child_subfield_navigation_target(
        self,
        child_identity: "InlineDataclassChildFieldIdentity",
        relative_path: "StructuralValuePath",
    ) -> "StructuralFlashTarget | None":
        """Return a concrete visual target for a child structural path.

        An empty ``relative_path`` represents the child structural owner itself.
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


class InlineDataclassRootResettable(ABC):
    """ABC for inline dataclass widgets that can reset their child fields."""

    @abstractmethod
    def reset_inline_dataclass_fields(self) -> None:
        """Reset the inline dataclass child fields to their signature defaults."""
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


class PlaceholderStateTrackable(WidgetCapabilityTagged):
    """ABC for widgets that own placeholder chrome/cache state."""

    widget_capabilities: ClassVar[frozenset[WidgetCapability]] = frozenset(
        {WidgetCapability.PLACEHOLDER_STATE}
    )

    @abstractmethod
    def has_placeholder_state(self) -> bool:
        """Return whether placeholder chrome or cached placeholder data is present."""
        pass

    @abstractmethod
    def mark_placeholder_state(self) -> None:
        """Mark the widget as currently displaying placeholder chrome."""
        pass

    @abstractmethod
    def clear_placeholder_state(self) -> None:
        """Mark the widget as no longer displaying placeholder chrome."""
        pass

    @abstractmethod
    def cached_placeholder_text(self) -> str | None:
        """Return cached placeholder text, if any."""
        pass

    @abstractmethod
    def set_cached_placeholder_text(self, placeholder_text: str) -> None:
        """Cache placeholder text after a successful render."""
        pass

    @abstractmethod
    def cached_placeholder_resolved_value(self) -> Any:
        """Return cached placeholder resolved value, if any."""
        pass

    @abstractmethod
    def set_cached_placeholder_resolved_value(self, value: Any) -> None:
        """Cache the resolved value after a successful preview render."""
        pass

    @abstractmethod
    def clear_placeholder_cache(self) -> None:
        """Clear cached placeholder text and resolved value."""
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
