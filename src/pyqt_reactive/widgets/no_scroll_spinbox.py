"""
No-scroll spinbox widgets for PyQt6.

Prevents accidental value changes from mouse wheel events.
"""

from enum import Enum
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QWheelEvent
from PyQt6.QtWidgets import (
    QApplication,
    QStyle,
    QStyleOptionButton,
    QStyleOptionComboBox,
)

# Import adapters that already implement ValueGettable/ValueSettable
from pyqt_reactive.protocols import (
    ChangeSignalEmitter,
    ComboBoxAdapter,
    DoubleSpinBoxAdapter,
    PlaceholderStateMixin,
    PyQtWidgetMeta,
    ResolvedValuePreviewSettable,
    SpinBoxAdapter,
    ValueGettable,
    ValueSettable,
)
from pyqt_reactive.theming.themed_checkbox import (
    ThemedCheckBox,
    paint_themed_checkbox,
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





class InheritedCheckBox(
    PlaceholderStateMixin,
    ThemedCheckBox,
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

        # Prevent horizontal stretching - checkbox should only be as wide as its content
        from PyQt6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def _read_concrete_value(self):
        return self.isChecked()

    def is_placeholder(self):
        return self.has_placeholder_state()

    def _write_concrete_value(self, value):
        self.setChecked(bool(value))

    def _signal_sources(self):
        return ((self, self.stateChanged),)

    def _apply_draft_style(self):
        if self.has_placeholder_state():
            self._apply_placeholder_palette()
        else:
            self._apply_concrete_palette()





    def set_placeholder_preview(self, checked: bool) -> None:
        """Display an inherited checkbox value without making it concrete."""
        signals_blocked = self.blockSignals(True)
        try:
            self.setChecked(checked)

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
                "InheritedCheckBox resolved previews require bool or None values, "
                f"got {type(value).__name__}."
            )
        self.set_placeholder_preview(value)

    def convert_placeholder_to_concrete(self):
        self.clear_placeholder_state()
        self._apply_draft_style()

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

        paint_themed_checkbox(self, option, painter)
        painter.end()


# NoScrollSpinBox, NoScrollDoubleSpinBox, NoScrollComboBox inherit from adapters
# which are already registered, so no additional registration needed
