"""Responsive title layout for GroupBoxWithHelp."""

import logging

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from PyQt6.QtCore import QTimer, Qt

from pyqt_reactive.widgets.shared.responsive_layout_widgets import StagedWrapLayout
from typing import Optional, List, Tuple

# Global toggle for responsive wrapping
_wrapping_enabled = True

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

        # Transparent background so scope-tinted background shows through
        self.setAutoFillBackground(False)
        self.setStyleSheet("background-color: transparent;")

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(2)

        self._staged_layout = StagedWrapLayout(parent=self, spacing=5)
        self._main_layout.addWidget(self._staged_layout)
        
        # Storage
        self._title_widget: Optional[QWidget] = None
        self._help_widget: Optional[QWidget] = None
        self._inline_widgets: List[Tuple[QWidget, int]] = []
        self._right_widgets: List[Tuple[QWidget, int]] = []

        self._title_group = QWidget()
        self._title_layout = QHBoxLayout(self._title_group)
        self._title_layout.setContentsMargins(0, 0, 0, 0)
        self._title_layout.setSpacing(5)

        self._help_group = QWidget()
        self._help_layout = QHBoxLayout(self._help_group)
        self._help_layout.setContentsMargins(0, 0, 0, 0)
        self._help_layout.setSpacing(5)

        self._inline_group = QWidget()
        self._inline_layout = QHBoxLayout(self._inline_group)
        self._inline_layout.setContentsMargins(0, 0, 0, 0)
        self._inline_layout.setSpacing(5)
        self._inline_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self._right_group = QWidget()
        self._right_layout = QHBoxLayout(self._right_group)
        self._right_layout.setContentsMargins(0, 0, 0, 0)
        self._right_layout.setSpacing(5)

        # Help button stays inline with title (always left aligned)
        self._help_inline = True
        
        # Debounce timer
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._check_switch)
        
        if parent:
            parent.installEventFilter(self)
    
    def set_title_widget(self, widget):
        self._title_widget = widget
        self._title_layout.addWidget(widget)
        self._refresh_groups()
    
    def set_help_widget(self, widget):
        self._help_widget = widget
        if self._help_inline:
            self._title_layout.addWidget(widget)
        else:
            self._help_layout.addWidget(widget)
        self._refresh_groups()
    
    def minimumSizeHint(self):
        """Return minimum size - log for debugging."""
        from PyQt6.QtCore import QSize
        size = super().minimumSizeHint()
        return size
    
    def add_right_widget(self, widget, stretch=0):
        self._right_widgets.append((widget, stretch))
        self._right_layout.addWidget(widget, stretch)
        self._refresh_groups()
    
    def add_inline_widget(self, widget, stretch=0):
        """Add widget that stays with title in row1 (doesn't move to row2)."""
        self._inline_widgets.append((widget, stretch))
        self._inline_layout.addWidget(widget, stretch)
        self._refresh_groups()
    
    def insert_inline_widget(self, index, widget, stretch=0):
        """Insert widget at specific position in row1 (doesn't move to row2).
        
        This is used for inserting inline widgets at a specific position,
        such as right after the help button.
        """
        # Track as inline widget so it stays with title in vertical mode
        if widget not in [w for w, _ in self._inline_widgets]:
            self._inline_widgets.append((widget, stretch))
        self._inline_layout.insertWidget(index, widget, stretch)
        self._refresh_groups()
    
    def _check_switch(self):
        # Skip if wrapping is globally disabled
        if not _wrapping_enabled:
            return
        self._refresh_groups()
    
    def _calc_width(self):
        from PyQt6.QtWidgets import QLabel
        from PyQt6.QtGui import QFontMetrics
        
        total = 0
        spacing = self._title_layout.spacing()
        
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
        
        margins = self._title_layout.contentsMargins()
        total += margins.left() + margins.right()
        
        return total
    
    def _do_switch(self):
        self._refresh_groups()
    
    def eventFilter(self, a0, a1):
        if a1 is not None and a1.type() == a1.Type.Resize:
            self._timer.start(100)
        return super().eventFilter(a0, a1)
    
    # Compatibility methods for QHBoxLayout API
    def count(self):
        """Return total widget count across both rows (for compatibility)."""
        return self._title_layout.count() + self._help_layout.count() + self._inline_layout.count() + self._right_layout.count()
    
    def insertWidget(self, index, widget, stretch=0):
        """Insert widget at position (for compatibility - adds to inline widgets)."""
        # Track as inline widget so it stays with title in vertical mode
        if widget not in [w for w, _ in self._inline_widgets]:
            self._inline_widgets.append((widget, stretch))
        self._inline_layout.insertWidget(index, widget, stretch)
    
    def itemAt(self, index):
        """Get item at index (for compatibility - from row1)."""
        layouts = [self._title_layout, self._help_layout, self._inline_layout, self._right_layout]
        current = 0
        for layout in layouts:
            if index < current + layout.count():
                return layout.itemAt(index - current)
            current += layout.count()
        return None
    
    def spacerItem(self):
        """Check if there's a spacer (for compatibility)."""
        return None  # We don't use spacers in the same way

    def _refresh_groups(self):
        if self._help_inline:
            groups = [
                ("title", self._title_group),
                ("inline", self._inline_group),
                ("right", self._right_group),
            ]
            stay_priority = ["title", "inline", "right"]
        else:
            groups = [
                ("title", self._title_group),
                ("help", self._help_group),
                ("inline", self._inline_group),
                ("right", self._right_group),
            ]
            stay_priority = ["title", "help", "inline", "right"]

        self._staged_layout.set_groups(
            groups,
            stay_priority,
            right_align_names=["right"],
        )
