"""
Widget adapters that wrap Qt widgets to implement OpenHCS ABCs.

Normalizes Qt's inconsistent APIs:
- QLineEdit.text() vs QSpinBox.value() vs QComboBox.currentData()
- QLineEdit.setText() vs QSpinBox.setValue() vs QComboBox.setCurrentIndex()
- QLineEdit.setPlaceholderText() vs QSpinBox.setSpecialValueText()

All adapters implement consistent interface via ABCs:
- get_value() / set_value() for all widgets
- set_placeholder() for all widgets
- connect_change_signal() for all widgets

Mirrors MemoryTypeConverter pattern - adapters normalize inconsistent APIs.
"""

from abc import ABCMeta
from collections.abc import Callable
from enum import Enum
from typing import Any
from objectstate.field_value import FieldValue, Inherit, Unset, Value

try:
    from PyQt6.QtCore import QLocale, QObject
    from PyQt6.QtGui import QKeySequence
    from PyQt6.QtWidgets import (
        QComboBox,
        QDoubleSpinBox,
        QGroupBox,
        QKeySequenceEdit,
        QLineEdit,
        QSpinBox,
        QWidget,
    )

    from pyqt_reactive.theming.themed_checkbox import ThemedCheckBox
    PYQT6_AVAILABLE = True
    # PyQt-specific metaclass that combines ABCMeta with Qt's metaclass
    # Order matters: ABCMeta first (it's the "primary" metaclass for ABC functionality)
    _QtMetaclass = type(QObject)
    class PyQtWidgetMeta(_QtMetaclass, ABCMeta):
        """Metaclass for PyQt widgets that need ABC support."""
        pass
except ImportError:
    PYQT6_AVAILABLE = False
    # Create dummy base classes for type hints
    QLineEdit = QSpinBox = QDoubleSpinBox = QComboBox = object
    ThemedCheckBox = QKeySequenceEdit = QWidget = object
    PyQtWidgetMeta = ABCMeta

from .widget_protocols import (
    ChangeSignalEmitter,
    PlaceholderCapable,
    PlaceholderStateTrackable,
    RangeConfigurable,
    ResolvedValuePreviewSettable,
    ValueGettable,
    ValueSettable,
    WidgetCapability,
    widget_supports_capability,
)

if PYQT6_AVAILABLE:

    class WidgetValue(Value):
        """A concrete draft read from its control, not a second stored model value."""
        __slots__ = ('reader',)

        def __init__(self, reader):
            self.reader = reader

        @property
        def value(self):
            return self.reader()


    class PlaceholderStateMixin(PlaceholderStateTrackable):
        """Own one input draft and its native signal subscriptions.

        Inherit and Unset are retained as distinct input states. Concrete input lives
        in the Qt control and is read lazily, so incomplete text is not parsed while
        the user is typing. Model paints never publish input events.
        """
        widget_capabilities = frozenset({WidgetCapability.PLACEHOLDER_STATE})

        def __init__(self, *args, **kwargs):
            self._draft = Unset()
            self._input_callbacks = []
            self._native_connections = {}
            self._cached_placeholder_text = None
            self._cached_placeholder_resolved_value = None
            super().__init__(*args, **kwargs)

        def _signal_sources(self):
            return ()

        def _ensure_input_tracking(self):
            for owner, signal in self._signal_sources():
                if owner not in self._native_connections:
                    signal.connect(self._native_input)
                    self._native_connections[owner] = signal

        def _native_input(self, *arguments):
            self.clear_placeholder_state()
            self._prepare_input()
            self._draft = WidgetValue(self._read_concrete_value)
            self.clear_placeholder_cache()
            self._apply_draft_style()
            for callback in tuple(self._input_callbacks):
                callback(self.get_value())

        def _prepare_input(self):
            pass

        def _apply_draft_style(self):
            pass

        def _read_concrete_value(self):
            raise TypeError(f"{type(self).__name__} does not own a concrete input control")

        def _write_blank_value(self, value):
            self._write_concrete_value(None)

        def get_value(self):
            self._ensure_input_tracking()
            return self._draft.resolve(lambda: Inherit())

        def set_value(self, value):
            self._ensure_input_tracking()
            draft = FieldValue.of(value)
            if self._draft.inherited and not draft.inherited:
                self.clear_placeholder_state()
            previous = self.blockSignals(True)
            try:
                self._draft = draft
                if draft.has_value:
                    self._write_concrete_value(value)
                    if value is not None:
                        self._draft = WidgetValue(self._read_concrete_value)
                else:
                    self._write_blank_value(value)
                self._apply_draft_style()
            finally:
                self.blockSignals(previous)

        def connect_change_signal(self, callback):
            self._ensure_input_tracking()
            if callback not in self._input_callbacks:
                self._input_callbacks.append(callback)

        def disconnect_change_signal(self, callback):
            if callback in self._input_callbacks:
                self._input_callbacks.remove(callback)

        def has_placeholder_state(self):
            return self._draft.inherited

        def mark_placeholder_state(self):
            self._draft = Inherit()

        def clear_placeholder_state(self):
            if self._draft.inherited:
                self.setStyleSheet("")
                self._draft = WidgetValue(self._read_concrete_value)
            self.clear_placeholder_cache()

        def cached_placeholder_text(self):
            return self._cached_placeholder_text

        def set_cached_placeholder_text(self, text):
            self._cached_placeholder_text = text

        def cached_placeholder_resolved_value(self):
            return self._cached_placeholder_resolved_value

        def set_cached_placeholder_resolved_value(self, value):
            self._cached_placeholder_resolved_value = value

        def clear_placeholder_cache(self):
            self._cached_placeholder_text = None
            self._cached_placeholder_resolved_value = None



    class LineEditAdapter(PlaceholderStateMixin, QLineEdit, ValueGettable, ValueSettable, PlaceholderCapable,
                          ChangeSignalEmitter, metaclass=PyQtWidgetMeta):
        """
        Adapter for QLineEdit implementing OpenHCS ABCs.
        
        Normalizes Qt API to OpenHCS contracts:
        - .text() → .get_value()
        - .setText() → .set_value()
        - .setPlaceholderText() → .set_placeholder()
        - .textChanged → .connect_change_signal()
        """
        
        _widget_id = "line_edit"
        
        def _read_concrete_value(self) -> Any:
            """Implement ValueGettable ABC."""
            text = self.text().strip()
            return text
        
        def _write_concrete_value(self, value: Any) -> None:
            """Implement ValueSettable ABC."""
            self.setText("" if value is None else str(value))
        
        def set_placeholder(self, text: str) -> None:
            """Implement PlaceholderCapable ABC."""
            self.setPlaceholderText(text)
        
        

        def _signal_sources(self):
            return ((self, self.textChanged),)
    class KeySequenceEditAdapter(
        PlaceholderStateMixin,
        QKeySequenceEdit,
        ValueGettable,
        ValueSettable,
        ChangeSignalEmitter,
        metaclass=PyQtWidgetMeta,
    ):
        """Capture complete portable Qt key sequences before committing them."""

        _widget_id = "key_sequence_edit"


        def _read_concrete_value(self) -> str:
            """Return the complete key sequence in portable text form."""

            return self.keySequence().toString(
                QKeySequence.SequenceFormat.PortableText
            )

        def _write_concrete_value(self, value: Any) -> None:
            """Assign a portable key sequence."""

            self.setKeySequence(QKeySequence("" if value is None else str(value)))



        def _signal_sources(self):
            return ((self, self.editingFinished),)


    class SpinBoxAdapter(PlaceholderStateMixin, QSpinBox, ValueGettable, ValueSettable, PlaceholderCapable,
                         RangeConfigurable, ChangeSignalEmitter, metaclass=PyQtWidgetMeta):
        """
        Adapter for QSpinBox implementing OpenHCS ABCs.
        
        Handles None values using special value text mechanism.
        When value is None, displays placeholder text at minimum value.
        """
        
        _widget_id = "spin_box"
        
        def __init__(self, parent=None):
            super().__init__(parent)
            # Configure for None-aware behavior
            self.setSpecialValueText(" ")  # Empty special value = None
            self.setRange(-2147483648, 2147483647)  # Default int range
        
        def _read_concrete_value(self):
            return self.value()
        
        def _write_concrete_value(self, value: Any) -> None:
            """Implement ValueSettable ABC."""
            if value is None:
                self.setValue(self.minimum())
            else:
                self.setValue(int(value))
        
        def set_placeholder(self, text: str) -> None:
            """Implement PlaceholderCapable ABC."""
            # For spinbox, placeholder is shown when at minimum with special value text
            self.setSpecialValueText(text)
        
        def configure_range(self, minimum: float, maximum: float) -> None:
            """Implement RangeConfigurable ABC."""
            self.setRange(int(minimum), int(maximum))
        
        

        def _signal_sources(self):
            return ((self, self.valueChanged),)
    
    
    class DoubleSpinBoxAdapter(PlaceholderStateMixin, QDoubleSpinBox, ValueGettable, ValueSettable,
                               PlaceholderCapable, RangeConfigurable,
                               ChangeSignalEmitter, metaclass=PyQtWidgetMeta):
        """
        Adapter for QDoubleSpinBox implementing OpenHCS ABCs.
        
        Handles None values and floating-point ranges.
        """
        
        _widget_id = "double_spin_box"
        
        def __init__(self, parent=None):
            from pyqt_reactive.forms.widget_strategies import WidgetConfig
            super().__init__(parent)
            self.setSpecialValueText(" ")
            self.setRange(-1e308, 1e308)  # Default float range
            self.setDecimals(WidgetConfig.FLOAT_PRECISION)  # Use configured precision

        def textFromValue(self, value: float) -> str:  # noqa: N802 - Qt virtual method
            """Display the shortest localized decimal that preserves the value."""
            locale = self.locale()
            options = locale.numberOptions()
            if self.isGroupSeparatorShown():
                options &= ~QLocale.NumberOption.OmitGroupSeparator
            else:
                options |= QLocale.NumberOption.OmitGroupSeparator
            locale.setNumberOptions(options)
            return locale.toString(
                value, "f", QLocale.FloatingPointPrecisionOption.FloatingPointShortest
            )
        
        def _read_concrete_value(self):
            return self.value()
        
        def _write_concrete_value(self, value: Any) -> None:
            """Implement ValueSettable ABC."""
            if value is None:
                self.setValue(self.minimum())
            else:
                self.setValue(float(value))
        
        def set_placeholder(self, text: str) -> None:
            """Implement PlaceholderCapable ABC."""
            self.setSpecialValueText(text)
        
        def configure_range(self, minimum: float, maximum: float) -> None:
            """Implement RangeConfigurable ABC."""
            self.setRange(minimum, maximum)
        
        

        def _signal_sources(self):
            return ((self, self.valueChanged),)
    
    
    class ComboBoxAdapter(PlaceholderStateMixin, QComboBox, ValueGettable, ValueSettable, PlaceholderCapable,
                         ChangeSignalEmitter, metaclass=PyQtWidgetMeta):
        """
        Adapter for QComboBox implementing OpenHCS ABCs.
        
        Stores actual values in itemData, not just display text.
        Supports enum population and selection.
        """
        
        _widget_id = "combo_box"
        
        def _read_concrete_value(self) -> Any:
            """Implement ValueGettable ABC."""
            if self.currentIndex() < 0:
                return Unset()
            return self.itemData(self.currentIndex())
        
        def _write_concrete_value(self, value: Any) -> None:
            """Implement ValueSettable ABC."""
            # Find index of item with matching data
            for i in range(self.count()):
                if self.itemData(i) == value:
                    self.setCurrentIndex(i)
                    return
            # Value not found - clear selection
            self.setCurrentIndex(-1)
        
        def set_placeholder(self, text: str) -> None:
            """Implement PlaceholderCapable ABC."""
            # ComboBox placeholder is shown when no selection
            self.setPlaceholderText(text)
        
        def populate_enum(self, enum_type: type) -> None:
            """
            Populate combobox with enum values.
            
            Args:
                enum_type: The Enum class to populate from
            """
            if not isinstance(enum_type, type) or not issubclass(enum_type, Enum):
                raise TypeError(f"{enum_type} is not an Enum type")
            
            self.clear()
            for enum_value in enum_type:
                self.addItem(enum_value.name, enum_value)
        
        

        def _signal_sources(self):
            return ((self, self.currentIndexChanged),)
    
    
    class CheckBoxAdapter(PlaceholderStateMixin, ThemedCheckBox, ValueGettable, ValueSettable,
                         ChangeSignalEmitter, metaclass=PyQtWidgetMeta):
        """
        Adapter for QCheckBox implementing OpenHCS ABCs.

        Returns bool values, treats None as False.
        """

        _widget_id = "check_box"

        def _read_concrete_value(self) -> Any:
            """Implement ValueGettable ABC."""
            return self.isChecked()

        def _write_concrete_value(self, value: Any) -> None:
            """Implement ValueSettable ABC."""
            self.setChecked(bool(value) if value is not None else False)



        def _signal_sources(self):
            return ((self, self.stateChanged),)


    class CheckboxGroupAdapter(PlaceholderStateMixin, QGroupBox, ValueGettable, ValueSettable,
                               ResolvedValuePreviewSettable, ChangeSignalEmitter,
                               metaclass=PyQtWidgetMeta):
        """
        Adapter for checkbox group (List[Enum]) implementing OpenHCS ABCs.

        Manages a group of InheritedCheckBox widgets for multi-selection.
        Returns List[Enum] or None (for placeholder state).

        This eliminates duck typing - instead of checking for _checkboxes attribute,
        we use proper ABC inheritance.
        """

        _widget_id = "checkbox_group"

        def __init__(self, parent=None):
            super().__init__(parent)
            # Dictionary mapping enum values to checkbox widgets
            self._checkboxes = {}

        def checkbox_items(self) -> tuple[tuple[Any, Any], ...]:
            """Return enum-to-checkbox items for group-level placeholder logic."""
            return tuple(self._checkboxes.items())

        def checkbox_widgets(self) -> tuple[Any, ...]:
            """Return checkboxes managed by this group."""
            return tuple(self._checkboxes.values())

        def _read_concrete_value(self):
            return [value for value, checkbox in self.checkbox_items() if checkbox.isChecked()]

        def _write_concrete_value(self, value):
            for member, checkbox in self.checkbox_items():
                checkbox.set_value(member in value if value is not None else False)

        def set_resolved_value_preview(self, value: Any) -> None:
            """Preview a resolved enum list while preserving raw placeholder state."""
            if value is None:
                inherited_values = frozenset()
            elif isinstance(value, list):
                inherited_values = frozenset(value)
            else:
                raise TypeError(
                    "CheckboxGroupAdapter resolved previews must be list or None, "
                    f"got {type(value).__name__}."
                )

            for enum_value, checkbox in self.checkbox_items():
                if not isinstance(checkbox, ResolvedValuePreviewSettable):
                    raise TypeError(
                        "Checkbox group children must implement "
                        "ResolvedValuePreviewSettable."
                    )
                checkbox.set_resolved_value_preview(enum_value in inherited_values)
            self.mark_placeholder_state()





        def _signal_sources(self):
            return tuple((checkbox, checkbox.stateChanged) for checkbox in self.checkbox_widgets())

        def _prepare_input(self):
            for checkbox in self.checkbox_widgets():
                checkbox.convert_placeholder_to_concrete()

        def _write_blank_value(self, value):
            for checkbox in self.checkbox_widgets():
                checkbox.set_value(value)


# Manual registration of adapters in WIDGET_IMPLEMENTATIONS
# (PyQtWidgetMeta doesn't auto-register like WidgetMeta does)
if PYQT6_AVAILABLE:
    from .widget_protocols import (
        ChangeSignalEmitter,
        PlaceholderCapable,
        PlaceholderStateTrackable,
        RangeConfigurable,
        ResolvedValuePreviewSettable,
        ValueGettable,
        ValueSettable,
    )

    # Register all adapter classes
    adapters = [
        LineEditAdapter,
        SpinBoxAdapter,
        DoubleSpinBoxAdapter,
        ComboBoxAdapter,
        CheckBoxAdapter,
        CheckboxGroupAdapter,
    ]

    for adapter_class in adapters:
        widget_id = adapter_class._widget_id

        # Track capabilities
        capabilities = set()
        abc_types = {
            ValueGettable, ValueSettable, PlaceholderCapable,
            PlaceholderStateTrackable, RangeConfigurable, ChangeSignalEmitter,
            ResolvedValuePreviewSettable,
        }

        for abc_type in abc_types:
            if issubclass(adapter_class, abc_type):
                capabilities.add(abc_type)
