"""Responsive title layout for GroupBoxWithHelp."""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from PyQt6.QtCore import QTimer
from typing import Optional, List, Tuple

# Global toggle for responsive wrapping - default to False (old non-wrapping style)
_wrapping_enabled = False

def set_wrapping_enabled(enabled: bool):
    """Globally enable or disable responsive wrapping for all GroupBox titles."""
    global _wrapping_enabled
    _wrapping_enabled = enabled

def is_wrapping_enabled() -> bool:
    """Check if responsive wrapping is globally enabled."""
    return _wrapping_enabled


class ResponsiveGroupBoxTitle(QWidget):
    """
    Responsive title widget that switches between 1-row and 2-row layout.
    
    Row 1: [Title] [Help] [inline widgets]
    Row 2: [Reset All] [Enabled] etc. - only when narrow
    """
    
    def __init__(self, parent=None, width_threshold: int = 300):
        super().__init__(parent)
        self._threshold = width_threshold
        self._is_horizontal = True
        
        # Main layout (vertical)
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(2)
        
        # Row 1: Title and inline widgets
        self._row1 = QWidget()
        self._row1_layout = QHBoxLayout(self._row1)
        self._row1_layout.setContentsMargins(0, 0, 0, 0)
        self._row1_layout.setSpacing(5)
        self._main_layout.addWidget(self._row1)
        
        # Row 2: Right-aligned widgets (hidden initially)
        self._row2 = QWidget()
        self._row2_layout = QHBoxLayout(self._row2)
        self._row2_layout.setContentsMargins(0, 0, 0, 0)
        self._row2_layout.setSpacing(5)
        self._main_layout.addWidget(self._row2)
        self._row2.hide()
        
        # Storage
        self._title_widget: Optional[QWidget] = None
        self._help_widget: Optional[QWidget] = None
        self._inline_widgets: List[Tuple[QWidget, int]] = []
        self._right_widgets: List[Tuple[QWidget, int]] = []
        
        # Debounce timer
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._check_switch)
        
        if parent:
            parent.installEventFilter(self)
    
    def set_title_widget(self, widget):
        self._title_widget = widget
        self._row1_layout.addWidget(widget)
    
    def set_help_widget(self, widget):
        self._help_widget = widget
        self._row1_layout.addWidget(widget)
    
    def add_right_widget(self, widget, stretch=0):
        self._right_widgets.append((widget, stretch))
        self._row1_layout.addWidget(widget, stretch)
    
    def add_inline_widget(self, widget, stretch=0):
        """Add widget that stays with title in row1 (doesn't move to row2)."""
        self._inline_widgets.append((widget, stretch))
        self._row1_layout.addWidget(widget, stretch)
    
    def _check_switch(self):
        # Skip if wrapping is globally disabled
        if not _wrapping_enabled:
            return
        
        available = self.parent().width() if self.parent() else self.width()
        content = self._calc_width()
        
        # Switch immediately when content exceeds available space
        if self._is_horizontal:
            if available < content:
                self._is_horizontal = False
                self._do_switch()
        else:
            if available > (content + 20):
                self._is_horizontal = True
                self._do_switch()
    
    def _calc_width(self):
        from PyQt6.QtWidgets import QLabel
        from PyQt6.QtGui import QFontMetrics
        
        total = 0
        spacing = self._row1_layout.spacing()
        
        def get_width(w):
            if isinstance(w, QLabel) and w.text():
                fm = QFontMetrics(w.font())
                return fm.horizontalAdvance(w.text()) + 16
            return w.sizeHint().width()
        
        # Title and help always included
        if self._title_widget:
            total += get_width(self._title_widget)
        if self._help_widget:
            total += get_width(self._help_widget)
        
        # Inline widgets (always with title)
        for w, _ in self._inline_widgets:
            total += get_width(w)
        
        # Count widgets for spacing calculation
        widget_count = (1 if self._title_widget else 0) + (1 if self._help_widget else 0) + len(self._inline_widgets)
        
        # Right widgets only counted in horizontal mode
        if self._is_horizontal:
            for w, _ in self._right_widgets:
                total += get_width(w)
            widget_count += len(self._right_widgets)
        
        # Add spacing between widgets
        if widget_count > 1:
            total += spacing * (widget_count - 1)
        
        margins = self._row1_layout.contentsMargins()
        total += margins.left() + margins.right()
        
        return total
    
    def _do_switch(self):
        if self._is_horizontal:
            # Horizontal mode: Title | Help | Inline | Stretch | Right widgets
            self._row2.setVisible(False)
            while self._row1_layout.count():
                item = self._row1_layout.takeAt(0)
                if item:
                    del item
            # Row 1: Title first
            if self._title_widget:
                self._row1_layout.addWidget(self._title_widget)
            # Then help
            if self._help_widget:
                self._row1_layout.addWidget(self._help_widget)
            # Then inline widgets (checkmark, reset)
            for w, s in self._inline_widgets:
                self._row1_layout.addWidget(w, s)
            # Stretch to push right widgets to far right
            self._row1_layout.addStretch(1)
            # Right widgets at far right (Reset All)
            for w, s in self._right_widgets:
                self._row2_layout.removeWidget(w)
                self._row1_layout.addWidget(w, s)
        else:
            # Vertical mode:
            # Row 1: Title only
            while self._row1_layout.count():
                item = self._row1_layout.takeAt(0)
                if item:
                    del item
            if self._title_widget:
                self._row1_layout.addWidget(self._title_widget)
            
            # Row 2: Help | Inline | Stretch | Right
            while self._row2_layout.count():
                item = self._row2_layout.takeAt(0)
                if item:
                    del item
            # Help first
            if self._help_widget:
                self._row2_layout.addWidget(self._help_widget)
            # Inline widgets (checkmark, reset)
            for w, s in self._inline_widgets:
                self._row1_layout.removeWidget(w)
                self._row2_layout.addWidget(w, s)
            # Stretch to push right widgets right
            self._row2_layout.addStretch(1)
            # Right widgets at far right (Reset All)
            for w, s in self._right_widgets:
                self._row1_layout.removeWidget(w)
                self._row2_layout.addWidget(w, s)
            self._row2.setVisible(True)
    
    def eventFilter(self, watched, event):
        if event.type() == event.Type.Resize:
            self._timer.start(100)
        return super().eventFilter(watched, event)
    
    # Compatibility methods for QHBoxLayout API
    def count(self):
        """Return total widget count across both rows (for compatibility)."""
        return self._row1_layout.count() + (self._row2_layout.count() if not self._is_horizontal else 0)
    
    def insertWidget(self, index, widget, stretch=0):
        """Insert widget at position (for compatibility - adds to inline widgets)."""
        # Track as inline widget so it stays with title in vertical mode
        if widget not in [w for w, _ in self._inline_widgets]:
            self._inline_widgets.append((widget, stretch))
        self._row1_layout.insertWidget(index, widget, stretch)
    
    def itemAt(self, index):
        """Get item at index (for compatibility - from row1)."""
        return self._row1_layout.itemAt(index)
    
    def spacerItem(self):
        """Check if there's a spacer (for compatibility)."""
        return None  # We don't use spacers in the same way
