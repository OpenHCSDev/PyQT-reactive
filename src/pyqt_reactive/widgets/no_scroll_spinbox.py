"""
No-scroll spinbox widgets for PyQt6.

Prevents accidental value changes from mouse wheel events.
"""

from enum import Enum
from typing import Callable

from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QStyle,
    QStyleOptionButton,
    QStyleOptionComboBox,
)
from PyQt6.QtGui import QWheelEvent, QFont, QColor, QPainter
from PyQt6.QtCore import Qt

# Import adapters that already implement ValueGettable/ValueSettable
from pyqt_reactive.protocols import (
    ComboBoxAdapter,
    ChangeSignalEmitter,
    DoubleSpinBoxAdapter,
    PlaceholderStateMixin,
    PyQtWidgetMeta,
    ResolvedValuePreviewSettable,
    SpinBoxAdapter,
    ValueGettable,
    ValueSettable,
)


class IgnoreWheelEventMixin:
    """Shared wheel-event policy for widgets that should not scroll values."""

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()


class NoScrollSpinBox(IgnoreWheelEventMixin, SpinBoxAdapter):
    """SpinBox that ignores wheel events to prevent accidental value changes.

    Inherits from SpinBoxAdapter which already implements ValueGettable/ValueSettable ABCs.
    """

class NoScrollDoubleSpinBox(IgnoreWheelEventMixin, DoubleSpinBoxAdapter):
    """DoubleSpinBox that ignores wheel events to prevent accidental value changes.

    Inherits from DoubleSpinBoxAdapter which already implements ValueGettable/ValueSettable ABCs.
    """

    def textFromValue(self, value: float) -> str:
        """Convert value to string without trailing zeros for clean display.

        Users can still type additional digits when editing - this only affects
        the display format, not the underlying precision.

        Examples:
            1.5 -> "1.5"
            1.0 -> "1"
            1.567 -> "1.567"
            0.0001 -> "0.0001"
        """
        # Format with all available precision first
        text = super().textFromValue(value)

        # Remove trailing zeros after decimal point
        if '.' in text:
            text = text.rstrip('0').rstrip('.')

        if text:
            return text
        return '0'


class NoScrollComboBox(IgnoreWheelEventMixin, ComboBoxAdapter):
    """ComboBox that ignores wheel events to prevent accidental value changes.

    Inherits from ComboBoxAdapter which already implements ValueGettable/ValueSettable ABCs.
    Supports placeholder text when currentIndex == -1 (for None values).
    """

    def __init__(self, parent=None, placeholder=""):
        super().__init__(parent)
        self._placeholder = placeholder
        self._placeholder_active = True

    def setPlaceholder(self, text: str):
        """Set the placeholder text shown when currentIndex == -1."""
        self._placeholder = text
        self.update()

    def setCurrentIndex(self, index: int):
        """Override to track when placeholder should be active."""
        super().setCurrentIndex(index)
        self._placeholder_active = (index == -1)
        self.update()

    def get_value(self):
        """Implement ValueGettable ABC."""
        if self.currentIndex() < 0:
            return None
        return self.itemData(self.currentIndex())

    def set_value(self, value):
        """Implement ValueSettable ABC."""
        # Find index of item with matching data
        for i in range(self.count()):
            if self.itemData(i) == value:
                self.setCurrentIndex(i)
                return
        # Value not found - clear selection
        self.setCurrentIndex(-1)

    def get_value(self):
        """Get current value (item data at current index)."""
        if self.currentIndex() < 0:
            return None
        return self.itemData(self.currentIndex())

    def set_value(self, value):
        """Set current value by finding matching item data."""
        if value is None:
            self.setCurrentIndex(-1)
        else:
            for i in range(self.count()):
                if self.itemData(i) == value:
                    self.setCurrentIndex(i)
                    return
            # Value not found - clear selection
            self.setCurrentIndex(-1)

    def paintEvent(self, event):
        """Override to draw placeholder text when currentIndex == -1."""
        if self._placeholder_active and self.currentIndex() == -1 and self._placeholder:
            # Use regular QPainter to have full control over text rendering
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Draw the combobox frame using style
            option = QStyleOptionComboBox()
            self.initStyleOption(option)
            option.currentText = ""  # Don't let style draw the text
            self.style().drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option, painter, self)

            # Now manually draw the placeholder text with our styling
            placeholder_color = QColor("#888888")
            font = QFont(self.font())
            font.setItalic(True)

            painter.setPen(placeholder_color)
            painter.setFont(font)

            # Get the text rect from the style
            text_rect = self.style().subControlRect(
                QStyle.ComplexControl.CC_ComboBox,
                option,
                QStyle.SubControl.SC_ComboBoxEditField,
                self
            )

            # Draw the placeholder text
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._placeholder)
            painter.end()
        else:
            super().paintEvent(event)


class CheckboxValueState(Enum):
    """Value ownership state for None-aware checkboxes."""

    PLACEHOLDER = "placeholder"
    CONCRETE = "concrete"


class NoneAwareCheckBox(
    PlaceholderStateMixin,
    QCheckBox,
    ValueGettable,
    ValueSettable,
    ResolvedValuePreviewSettable,
    ChangeSignalEmitter,
    metaclass=PyQtWidgetMeta,
):
    """
    QCheckBox that supports None state for lazy dataclass contexts.

    Shows inherited value as grayed placeholder when value is None.
    Clicking converts placeholder to explicit value.
    """

    PLACEHOLDER_PAINT_OPACITY = 0.45

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value_state = CheckboxValueState.CONCRETE
        # Prevent horizontal stretching - checkbox should only be as wide as its content
        from PyQt6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def get_value(self):
        """Get value, returning None if in placeholder state."""
        if self.is_placeholder():
            return None
        return self.isChecked()

    def is_placeholder(self) -> bool:
        """Return whether the checkbox is currently displaying inherited state."""
        return self._value_state is CheckboxValueState.PLACEHOLDER

    def set_value(self, value):
        """Set value, handling None by leaving in placeholder state."""
        if value is None:
            # Don't change state - placeholder system will set the preview value
            self._value_state = CheckboxValueState.PLACEHOLDER
            # Set grey palette for placeholder checkmark
            self._apply_placeholder_palette()
        else:
            self._value_state = CheckboxValueState.CONCRETE
            self.setChecked(bool(value))
            # Restore normal palette
            self._apply_concrete_palette()

    def connect_change_signal(self, callback: Callable[[bool | None], None]) -> None:
        """Implement ChangeSignalEmitter ABC."""
        def emit_concrete_value() -> None:
            self.convert_placeholder_to_concrete()
            callback(self.get_value())

        self.stateChanged.connect(emit_concrete_value)

    def disconnect_change_signal(self, callback: Callable[[bool | None], None]) -> None:
        """Implement ChangeSignalEmitter ABC."""
        try:
            self.stateChanged.disconnect(callback)
        except TypeError:
            pass

    def set_placeholder_preview(self, checked: bool) -> None:
        """Display an inherited checkbox value without making it concrete."""
        signals_blocked = self.blockSignals(True)
        try:
            self.setChecked(checked)
            self._value_state = CheckboxValueState.PLACEHOLDER
            self.mark_placeholder_state()
            self._apply_placeholder_palette()
        finally:
            self.blockSignals(signals_blocked)

    def set_resolved_value_preview(self, value) -> None:
        """Display an inherited resolved bool while preserving raw None."""
        if value is None:
            self.set_placeholder_preview(False)
            return
        if not isinstance(value, bool):
            raise TypeError(
                "NoneAwareCheckBox resolved previews require bool or None values, "
                f"got {type(value).__name__}."
            )
        self.set_placeholder_preview(value)

    def convert_placeholder_to_concrete(self) -> None:
        """Keep the displayed value but mark it as a user-controlled value."""
        if not self.is_placeholder():
            return
        self._value_state = CheckboxValueState.CONCRETE
        self.clear_placeholder_state()
        self._apply_concrete_palette()

    def toggle(self) -> None:
        """Toggle as a user action, committing placeholder state first."""
        self.convert_placeholder_to_concrete()
        super().toggle()

    def _apply_placeholder_palette(self):
        """Apply grey palette to make checkmark dim like placeholder text."""
        from PyQt6.QtGui import QPalette
        palette = self.palette()
        placeholder_color = QColor(136, 136, 136)
        for role in (
            QPalette.ColorRole.Text,
            QPalette.ColorRole.WindowText,
            QPalette.ColorRole.ButtonText,
        ):
            palette.setColor(role, placeholder_color)
        self.setPalette(palette)

    def _apply_concrete_palette(self):
        """Restore normal palette for concrete values."""
        from PyQt6.QtGui import QPalette
        # Use application palette to get the proper text color for the theme
        app_palette = QApplication.palette()
        palette = self.palette()
        for role in (
            QPalette.ColorRole.Text,
            QPalette.ColorRole.WindowText,
            QPalette.ColorRole.ButtonText,
        ):
            palette.setColor(role, app_palette.color(role))
        self.setPalette(palette)

    def mousePressEvent(self, event):
        """On click, switch from placeholder to explicit value."""
        self.convert_placeholder_to_concrete()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        """Draw with placeholder styling.

        For placeholder state, draw the checkbox with grey text color
        to make the checkmark appear dimmed.
        """
        if not self.is_placeholder():
            # Concrete value: Normal styling
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self.PLACEHOLDER_PAINT_OPACITY)

        option = QStyleOptionButton()
        self.initStyleOption(option)
        for role in (
            option.palette.ColorRole.Text,
            option.palette.ColorRole.WindowText,
            option.palette.ColorRole.ButtonText,
        ):
            option.palette.setColor(role, QColor(136, 136, 136))

        self.style().drawControl(QStyle.ControlElement.CE_CheckBox, option, painter, self)
        painter.end()


# NoScrollSpinBox, NoScrollDoubleSpinBox, NoScrollComboBox inherit from adapters
# which are already registered, so no additional registration needed
