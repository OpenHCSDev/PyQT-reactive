"""
No-scroll spinbox widgets for PyQt6.

Prevents accidental value changes from mouse wheel events.
"""

from PyQt6.QtWidgets import QCheckBox, QStyleOptionComboBox, QStyle, QApplication
from PyQt6.QtGui import QWheelEvent, QFont, QColor, QPainter
from PyQt6.QtCore import Qt

# Import adapters that already implement ValueGettable/ValueSettable
from pyqt_reactive.protocols import SpinBoxAdapter, DoubleSpinBoxAdapter, ComboBoxAdapter


class NoScrollSpinBox(SpinBoxAdapter):
    """SpinBox that ignores wheel events to prevent accidental value changes.

    Inherits from SpinBoxAdapter which already implements ValueGettable/ValueSettable ABCs.
    """

    def wheelEvent(self, event: QWheelEvent):
        """Ignore wheel events to prevent accidental value changes."""
        event.ignore()


class NoScrollDoubleSpinBox(DoubleSpinBoxAdapter):
    """DoubleSpinBox that ignores wheel events to prevent accidental value changes.

    Inherits from DoubleSpinBoxAdapter which already implements ValueGettable/ValueSettable ABCs.
    """

    def wheelEvent(self, event: QWheelEvent):
        """Ignore wheel events to prevent accidental value changes."""
        event.ignore()

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

        return text if text else '0'


class NoScrollComboBox(ComboBoxAdapter):
    """ComboBox that ignores wheel events to prevent accidental value changes.

    Inherits from ComboBoxAdapter which already implements ValueGettable/ValueSettable ABCs.
    Supports placeholder text when currentIndex == -1 (for None values).
    """

    def __init__(self, parent=None, placeholder=""):
        super().__init__(parent)
        self._placeholder = placeholder
        self._placeholder_active = True

    def wheelEvent(self, event: QWheelEvent):
        """Ignore wheel events to prevent accidental value changes."""
        event.ignore()

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


class NoneAwareCheckBox(QCheckBox):
    """
    QCheckBox that supports None state for lazy dataclass contexts.

    Shows inherited value as grayed placeholder when value is None.
    Clicking converts placeholder to explicit value.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_placeholder = False
        # Prevent horizontal stretching - checkbox should only be as wide as its content
        from PyQt6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def get_value(self):
        """Get value, returning None if in placeholder state."""
        if self._is_placeholder:
            return None
        return self.isChecked()

    def set_value(self, value):
        """Set value, handling None by leaving in placeholder state."""
        if value is None:
            # Don't change state - placeholder system will set the preview value
            self._is_placeholder = True
            # Set grey palette for placeholder checkmark
            self._apply_placeholder_palette()
        else:
            self._is_placeholder = False
            self.setChecked(bool(value))
            # Restore normal palette
            self._apply_concrete_palette()

    def _apply_placeholder_palette(self):
        """Apply grey palette to make checkmark dim like placeholder text."""
        from PyQt6.QtGui import QPalette
        palette = self.palette()
        # Set text color to grey - this affects the checkmark color
        palette.setColor(QPalette.ColorRole.Text, QColor(136, 136, 136))  # Grey like placeholder text
        self.setPalette(palette)

    def _apply_concrete_palette(self):
        """Restore normal palette for concrete values."""
        from PyQt6.QtGui import QPalette
        # Use application palette to get the proper text color for the theme
        app_palette = QApplication.palette()
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Text, app_palette.color(QPalette.ColorRole.Text))
        self.setPalette(palette)

    def mousePressEvent(self, event):
        """On click, switch from placeholder to explicit value."""
        if self._is_placeholder:
            self._is_placeholder = False
            # Clear placeholder property so get_value returns actual boolean
            self.setProperty("is_placeholder_state", False)
            # Restore normal palette
            self._apply_concrete_palette()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        """Draw with placeholder styling.

        For placeholder state, draw the checkbox with grey text color
        to make the checkmark appear dimmed.
        """
        if not self._is_placeholder:
            # Concrete value: Normal styling
            super().paintEvent(event)
            return

        # Placeholder: Draw with grey text color to dim the checkmark
        from PyQt6.QtWidgets import QStyle, QStyleOptionButton
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Get the checkbox style option
        option = QStyleOptionButton()
        self.initStyleOption(option)
        
        # Set grey text color - this affects the checkmark color
        option.palette.setColor(option.palette.ColorRole.Text, QColor(136, 136, 136))
        
        # Draw the checkbox with the modified palette
        self.style().drawControl(QStyle.ControlElement.CE_CheckBox, option, painter, self)
        
        painter.end()


# Register NoneAwareCheckBox as implementing ValueGettable and ValueSettable
from pyqt_reactive.protocols import ValueGettable, ValueSettable
ValueGettable.register(NoneAwareCheckBox)
ValueSettable.register(NoneAwareCheckBox)

# NoScrollSpinBox, NoScrollDoubleSpinBox, NoScrollComboBox inherit from adapters
# which are already registered, so no additional registration needed
