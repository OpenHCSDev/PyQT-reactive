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
    from PyQt6.QtCore import QLocale, QObject, QSignalBlocker
    from PyQt6.QtGui import QKeySequence, QValidator
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
            for owner, signal, receiver in self._signal_sources():
                if owner not in self._native_connections:
                    signal.connect(receiver)
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

        def _write_null_value(self):
            self._write_concrete_value(None)

        def _write_blank_value(self, value):
            self._write_null_value()

        def get_value(self):
            self._ensure_input_tracking()
            return self._draft.resolve(lambda: Inherit())

        def set_value(self, value):
            self._ensure_input_tracking()
            draft = FieldValue.of(value)
            previous = self.blockSignals(True)
            try:
                self.clear_placeholder_state()
                self._draft = draft
                draft.present_to(self)
                self._apply_draft_style()
            finally:
                self.blockSignals(previous)

        def present_value(self, value):
            """Paint concrete data; numeric controls provide their null view."""
            if value is None:
                self._write_null_value()
            else:
                self._write_concrete_value(value)
                self._draft = WidgetValue(self._read_concrete_value)

        def present_directive(self, value):
            self._write_blank_value(value)

        def connect_change_signal(self, callback):
            self._ensure_input_tracking()
            if callback not in self._input_callbacks:
                self._input_callbacks.append(callback)

        def disconnect_change_signal(self, callback):
            if callback in self._input_callbacks:
                self._input_callbacks.remove(callback)

        def has_placeholder_state(self):
            return FieldValue.is_inherited(self._draft)

        def mark_placeholder_state(self):
            self._draft = Inherit()

        def clear_placeholder_state(self):
            if FieldValue.is_inherited(self._draft):
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
            return ((self, self.textChanged, self._native_input),)
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
            return ((self, self.editingFinished, self._native_input),)


    class SpinBoxValueAdapter(PlaceholderStateMixin):
        """Own numeric draft painting and native admission for both Qt spinboxes.

        Qt special-value text is only a view at its numeric minimum. The draft
        owns meaning: literal null displays None; directives display their
        placeholder. A real minimum remains ordinary numeric data.
        """

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setRange(*self._default_range)
            self._write_blank_value(self._draft)
            self._ensure_input_tracking()

        def _read_concrete_value(self):
            return self.value()

        def _write_concrete_value(self, value):
            self.setSpecialValueText("")
            self.setValue(self._numeric_type(value))

        def _paint_special_text(self, text):
            with QSignalBlocker(self):
                self.setSpecialValueText(text)
                self.setValue(self.minimum())

        def _write_null_value(self):
            self._paint_special_text("None")

        def _write_blank_value(self, value):
            self._paint_special_text(self.lineEdit().placeholderText() or repr(value))

        def set_placeholder(self, text):
            self.lineEdit().setPlaceholderText(text)
            with QSignalBlocker(self):
                self._draft.present_to(self)

        def configure_range(self, minimum, maximum):
            with QSignalBlocker(self):
                self.setRange(self._numeric_type(minimum), self._numeric_type(maximum))
                self.set_value(self._draft)

        def _signal_sources(self):
            return (
                (self, self.valueChanged, self._native_input),
                (self.lineEdit(), self.lineEdit().textEdited, self._native_text_input),
            )

        def _native_text_input(self, text):
            # Qt emits textEdited before updating its number. Changed numbers
            # are admitted by valueChanged; only an unchanged number needs
            # this path to turn a model directive/null into native input.
            if isinstance(self._draft, WidgetValue):
                return
            state, _text, _position = self.validate(text, len(text))
            if state == QValidator.State.Acceptable and self.valueFromText(text) == self.value():
                self._native_input()

        def _prepare_input(self):
            # Qt rewrites its editor even when assigning the same empty text.
            # Retire the special paint once; do not repaint partial native input.
            if self.specialValueText():
                self.setSpecialValueText("")


    class SpinBoxAdapter(SpinBoxValueAdapter, QSpinBox, ValueGettable, ValueSettable, PlaceholderCapable,
                         RangeConfigurable, ChangeSignalEmitter, metaclass=PyQtWidgetMeta):
        """
        Adapter for QSpinBox implementing OpenHCS ABCs.
        
        Shared draft behavior comes from SpinBoxValueAdapter.
        """
        
        _widget_id = "spin_box"
        _numeric_type = int
        _default_range = (-2147483648, 2147483647)
        
        
        
        
        
        
        

    
    
    class DoubleSpinBoxAdapter(SpinBoxValueAdapter, QDoubleSpinBox, ValueGettable, ValueSettable,
                               PlaceholderCapable, RangeConfigurable,
                               ChangeSignalEmitter, metaclass=PyQtWidgetMeta):
        """
        Adapter for QDoubleSpinBox implementing OpenHCS ABCs.
        
        Shared draft behavior with localized floating-point presentation.
        """
        
        _widget_id = "double_spin_box"
        _numeric_type = float
        _default_range = (-1e308, 1e308)
        
        def __init__(self, parent=None):
            from pyqt_reactive.forms.widget_strategies import WidgetConfig
            super().__init__(parent)
            with QSignalBlocker(self):
                self.setDecimals(WidgetConfig.FLOAT_PRECISION)

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
            return ((self, self.currentIndexChanged, self._native_input),)
    
    
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
            return ((self, self.stateChanged, self._native_input),)


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
            return tuple((checkbox, checkbox.stateChanged, self._native_input) for checkbox in self.checkbox_widgets())

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
