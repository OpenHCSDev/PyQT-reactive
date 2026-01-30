"""Responsive layout widgets for PyQt6 - Uses layout config from manager"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from PyQt6.QtCore import QTimer, Qt
from typing import Optional, Any

# Global toggle for responsive wrapping - default to False (old non-wrapping style)
_wrapping_enabled = False

def set_wrapping_enabled(enabled: bool):
    """Globally enable or disable responsive wrapping for all parameter rows."""
    global _wrapping_enabled
    _wrapping_enabled = enabled

def is_wrapping_enabled() -> bool:
    """Check if responsive wrapping is globally enabled."""
    return _wrapping_enabled


class ResponsiveTwoRowWidget(QWidget):
    """Widget that switches between 1-row (horizontal) and 2-row (vertical) layout."""
    
    def __init__(self, width_threshold: int = 400, parent=None, layout_config=None):
        super().__init__(parent)
        self._threshold = width_threshold
        self._layout_config = layout_config
        self._is_horizontal = True
        
        # Get spacing from layout config or use defaults
        spacing = getattr(layout_config, 'parameter_row_spacing', 2) if layout_config else 2
        margins = getattr(layout_config, 'parameter_row_margins', (1, 1, 1, 1)) if layout_config else (1, 1, 1, 1)
        
        # Two rows
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(spacing)
        
        # Row 1: Always visible, contains left widgets + maybe right widgets
        self._row1 = QWidget()
        self._row1_layout = QHBoxLayout(self._row1)
        self._row1_layout.setContentsMargins(*margins)
        self._row1_layout.setSpacing(spacing)
        self._main_layout.addWidget(self._row1)
        
        # Row 2: Only for right widgets in vertical mode
        self._row2 = QWidget(self)  # Explicitly parent to self
        self._row2.setWindowFlags(Qt.WindowType.Widget)  # Ensure it's a widget, not a window
        self._row2_layout = QHBoxLayout(self._row2)
        self._row2_layout.setContentsMargins(*margins)
        self._row2_layout.setSpacing(spacing)
        self._main_layout.addWidget(self._row2)
        self._row2.hide()  # Start hidden in horizontal mode
        
        # Storage
        self._left_widgets = []
        self._right_widgets = []
        self._h_stretches = 0
        
        # Debounce timer
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._check_switch)
        
        if parent:
            parent.installEventFilter(self)
    
    def add_left_widget(self, widget, stretch=0):
        """Add widget to left side (stays in row1)."""
        self._left_widgets.append((widget, stretch))
        self._row1_layout.addWidget(widget, stretch)
    
    def add_right_widget(self, widget, stretch=0):
        """Add widget to right side (moves between row1 and row2)."""
        self._right_widgets.append((widget, stretch))
        self._row1_layout.addWidget(widget, stretch)  # Start in row1
    
    def _check_switch(self):
        """Check if we need to switch layouts based on content width."""
        # Skip if wrapping is globally disabled
        if not _wrapping_enabled:
            return
        
        available_width = self.parent().width() if self.parent() else self.width()
        content_width = self._calculate_content_width()
        
        # Switch immediately when content exceeds available space (no hysteresis)
        if self._is_horizontal:
            # Wrap when content is wider than available
            needs_vertical = available_width < content_width
            if needs_vertical:
                self._is_horizontal = False
                self._do_switch()
        else:
            # Unwrap when we have enough space (add small buffer to prevent rapid switching)
            can_go_horizontal = available_width > (content_width + 20)
            if can_go_horizontal:
                self._is_horizontal = True
                self._do_switch()
    
    def _calculate_content_width(self) -> int:
        """Calculate the actual width needed for all widgets in a single row.
        
        Uses font metrics for text widgets to get actual text width, not just sizeHint.
        """
        from PyQt6.QtWidgets import QLabel, QLineEdit, QComboBox
        from PyQt6.QtGui import QFontMetrics
        
        total = 0
        spacing = self._row1_layout.spacing()
        
        def get_preferred_width(widget):
            """Get preferred width accounting for text content."""
            if isinstance(widget, QLabel) and widget.text():
                # Use font metrics to calculate actual text width
                fm = QFontMetrics(widget.font())
                text_width = fm.horizontalAdvance(widget.text())
                # Add padding for icon/margins (typical QLabel has ~8px padding)
                return text_width + 16
            else:
                # For other widgets, use sizeHint
                return widget.sizeHint().width()
        
        # Left widgets width
        for widget, _ in self._left_widgets:
            total += get_preferred_width(widget)
        
        # Add spacing between left and right
        if self._left_widgets and self._right_widgets:
            total += spacing
        
        # Right widgets width
        for widget, _ in self._right_widgets:
            total += get_preferred_width(widget)
        
        # Add margins
        margins = self._row1_layout.contentsMargins()
        total += margins.left() + margins.right()
        
        return total  # No minimum threshold - purely content-based
    
    def _do_switch(self):
        """Actually perform the layout switch."""
        if self._is_horizontal:
            # Switching to horizontal: hide row2 first, then move widgets
            self._row2.setVisible(False)
            # Rebuild row1: left widgets + stretch + right widgets
            while self._row1_layout.count():
                item = self._row1_layout.takeAt(0)
                if item:
                    del item
            for widget, stretch in self._left_widgets:
                self._row1_layout.addWidget(widget, stretch)
            # Only add separate stretch if no expanding widget on right
            has_expanding = any(s > 0 for _, s in self._right_widgets)
            if not has_expanding:
                self._row1_layout.addStretch(1)
            for widget, stretch in self._right_widgets:
                self._row2_layout.removeWidget(widget)
                self._row1_layout.addWidget(widget, stretch)
        else:
            # Switching to vertical: rebuild layouts first, then show row2
            # Rebuild row1 with only left widgets (no stretch)
            while self._row1_layout.count():
                item = self._row1_layout.takeAt(0)
                if item:
                    del item
            for widget, stretch in self._left_widgets:
                self._row1_layout.addWidget(widget, stretch)
            # Row2: right widgets with trailing stretch to push left
            while self._row2_layout.count():
                item = self._row2_layout.takeAt(0)
                if item:
                    del item
            for widget, stretch in self._right_widgets:
                self._row1_layout.removeWidget(widget)
                self._row2_layout.addWidget(widget, stretch)
            # Only add trailing stretch if no widget is expanding
            has_expanding = any(s > 0 for _, s in self._right_widgets)
            if not has_expanding:
                self._row2_layout.addStretch(1)
            # Now safe to show row2 (after all widgets are reparented)
            self._row2.setVisible(True)
    
    def eventFilter(self, watched, event):
        """Monitor parent resize events."""
        if event.type() == event.Type.Resize:
            self._timer.start(100)
        return super().eventFilter(watched, event)
    
    def minimumSizeHint(self):
        """Return minimum size for layout calculations."""
        from PyQt6.QtCore import QSize
        
        # Width: always need space for left widgets (they're always visible)
        min_width = 0
        spacing = self._row1_layout.spacing()
        
        for widget, _ in self._left_widgets:
            min_width += widget.minimumSizeHint().width()
        
        if len(self._left_widgets) > 1:
            min_width += spacing * (len(self._left_widgets) - 1)
        
        margins = self._row1_layout.contentsMargins()
        min_width += margins.left() + margins.right()
        
        # Height: need both rows when in vertical mode, one row when horizontal
        row1_height = self._row1.minimumSizeHint().height()
        row2_height = self._row2.minimumSizeHint().height()
        
        if self._is_horizontal:
            min_height = row1_height
        else:
            # Vertical mode: both rows + spacing between them
            main_spacing = self._main_layout.spacing()
            min_height = row1_height + main_spacing + row2_height
        
        return QSize(min_width, min_height)


class ResponsiveParameterRow(ResponsiveTwoRowWidget):
    """Row for PFM parameters."""
    
    def __init__(self, width_threshold=350, parent=None, layout_config=None):
        super().__init__(width_threshold=width_threshold, parent=parent, layout_config=layout_config)
    
    def set_label(self, widget):
        from PyQt6.QtWidgets import QSizePolicy
        widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        if hasattr(widget, 'setWordWrap'):
            # Allow root-level field labels to wrap for better readability
            widget.setWordWrap(True)
        self.add_left_widget(widget, 0)
    
    def set_input(self, widget):
        from PyQt6.QtWidgets import QSizePolicy
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.add_right_widget(widget, 1)
    
    def set_reset_button(self, widget):
        self.add_right_widget(widget, 0)
    
    def set_help_button(self, widget):
        self.add_right_widget(widget, 0)
