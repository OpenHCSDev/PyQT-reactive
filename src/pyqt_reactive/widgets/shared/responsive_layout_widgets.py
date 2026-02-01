"""Responsive layout widgets for PyQt6 - Uses layout config from manager"""

import logging

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFontMetrics
from typing import Optional, Any, List

# Global toggle for responsive wrapping
_wrapping_enabled = True

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
        self._row1.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)  # Fixed height
        self._row1_layout = QHBoxLayout(self._row1)
        self._row1_layout.setContentsMargins(*margins)
        self._row1_layout.setSpacing(spacing)
        self._main_layout.addWidget(self._row1)

        # Row 2: Only for right widgets in vertical mode
        self._row2 = QWidget(self)  # Explicitly parent to self
        self._row2.setWindowFlags(Qt.WindowType.Widget)  # Ensure it's a widget, not a window
        self._row2.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)  # Fixed height
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
        
        parent_widget = self.parent()
        if parent_widget and hasattr(parent_widget, 'width'):
            available_width = parent_widget.width()
        else:
            available_width = self.width()
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
            # Add stretch to push right widgets to the right
            self._row1_layout.addStretch(1)
            for widget, stretch in self._right_widgets:
                self._row2_layout.removeWidget(widget)
                self._row1_layout.addWidget(widget, stretch, Qt.AlignmentFlag.AlignRight)
        else:
            # Switching to vertical: rebuild layouts first, then show row2
            # Rebuild row1 with only left widgets (no stretch)
            while self._row1_layout.count():
                item = self._row1_layout.takeAt(0)
                if item:
                    del item
            for widget, stretch in self._left_widgets:
                self._row1_layout.addWidget(widget, stretch)
            # Row2: right widgets with trailing stretch to push them right
            while self._row2_layout.count():
                item = self._row2_layout.takeAt(0)
                if item:
                    del item
            # Add stretch first to push everything to the right
            self._row2_layout.addStretch(1)
            for widget, stretch in self._right_widgets:
                self._row1_layout.removeWidget(widget)
                self._row2_layout.addWidget(widget, stretch, Qt.AlignmentFlag.AlignRight)
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
        
        # Width: sum of left + right widgets in single row (conservative minimum)
        min_width = 0
        spacing = self._row1_layout.spacing()
        
        # Add left widgets
        for widget, _ in self._left_widgets:
            min_width += widget.minimumSizeHint().width()
        
        if len(self._left_widgets) > 1:
            min_width += spacing * (len(self._left_widgets) - 1)
        
        # Add right widgets (they need space too even in horizontal mode)
        for widget, _ in self._right_widgets:
            min_width += widget.minimumSizeHint().width()
        
        if len(self._right_widgets) > 0 and len(self._left_widgets) > 0:
            min_width += spacing  # Space between left and right
        
        if len(self._right_widgets) > 1:
            min_width += spacing * (len(self._right_widgets) - 1)
        
        margins = self._row1_layout.contentsMargins()
        min_width += margins.left() + margins.right()
        
        # Height: ONLY include visible rows
        row1_height = self._row1.minimumSizeHint().height()
        
        if self._is_horizontal:
            min_height = row1_height
        else:
            row2_height = self._row2.minimumSizeHint().height()
            main_spacing = self._main_layout.spacing()
            min_height = row1_height + main_spacing + row2_height
        
        size = QSize(min_width, min_height)
        logger = logging.getLogger(__name__)
        logger.debug(f"[ResponsiveTwoRowWidget] minimumSizeHint: {min_width}x{min_height}, "
                    f"is_horizontal={self._is_horizontal}, left_widgets={len(self._left_widgets)}, "
                    f"right_widgets={len(self._right_widgets)}")
        return size
    
    def sizeHint(self):
        """Return preferred size - only include visible content."""
        from PyQt6.QtCore import QSize
        
        # Width: max of row 1 or row 2 content
        row1_width = self._row1.sizeHint().width()
        row2_width = self._row2.sizeHint().width() if not self._is_horizontal else 0
        width = max(row1_width, row2_width)
        
        # Height: only visible rows
        row1_height = self._row1.sizeHint().height()
        
        if self._is_horizontal:
            height = row1_height
        else:
            row2_height = self._row2.sizeHint().height()
            main_spacing = self._main_layout.spacing()
            height = row1_height + main_spacing + row2_height
        
        return QSize(width, height)


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


class ResponsiveConfigHeader(QWidget):
    """Header widget for config windows that dynamically switches between 1-row and 2-row layout.
    
    Title stays on row 1. Buttons start on row 1 (single row mode) or move to row 2 (narrow mode).
    Threshold is dynamically calculated based on actual content width.
    
    Usage:
        header = ResponsiveConfigHeader(parent=self)
        header.set_title("Configure PipelineConfig")
        header.add_button(save_button)
        header.add_button(cancel_button)
        layout.addWidget(header)
    """
    
    def __init__(self, parent=None, color_scheme=None):
        super().__init__(parent)
        self._color_scheme = color_scheme
        self._buttons = []
        
        # Main vertical layout
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(4)
        
        # Row 1: Title (always visible)
        self._title_widget = QWidget()
        self._title_layout = QHBoxLayout(self._title_widget)
        self._title_layout.setContentsMargins(0, 0, 0, 0)
        self._title_layout.setSpacing(4)
        
        self._title_label = QLabel()
        self._title_label.setStyleSheet(
            f"font-weight: bold; font-size: 14px;"
            f"color: {color_scheme.to_hex(color_scheme.text_accent) if color_scheme else '#ffffff'};"
        )
        self._title_layout.addWidget(self._title_label)
        self._title_layout.addStretch()
        self._main_layout.addWidget(self._title_widget)
        
        # Row 2: Responsive buttons container
        self._buttons_container = ResponsiveTwoRowWidget(width_threshold=0, parent=self)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._buttons_container.add_left_widget(spacer, stretch=1)
        self._main_layout.addWidget(self._buttons_container)
        
        # Note: Wrapping should be enabled by application, not by individual widgets
        
        # Monitor size changes to update threshold
        if parent:
            parent.installEventFilter(self)
    
    def set_title(self, text: str):
        """Set the header title text."""
        self._title_label.setText(text)
    
    def add_button(self, button: QWidget):
        """Add a button to the right side (will wrap to second row when narrow)."""
        self._buttons.append(button)
        self._buttons_container.add_right_widget(button)
        # Update threshold after adding button
        self._update_threshold()
    
    def add_help_button(self, button: QWidget):
        """Add a help button next to the title (doesn't participate in wrapping)."""
        # Insert before the stretch
        self._title_layout.insertWidget(1, button)
    
    def _update_threshold(self):
        """Calculate optimal threshold based on current content width."""
        # Get current content width when laid out horizontally
        total_width = 0
        
        # Title width
        fm = self._title_label.fontMetrics()
        total_width += fm.horizontalAdvance(self._title_label.text()) + 16
        
        # All button widths + spacing
        spacing = 4  # Typical button spacing
        for button in self._buttons:
            total_width += button.sizeHint().width() + spacing
        
        # Add margins and padding
        total_width += 32  # Generous padding
        
        # Set threshold (add buffer to prevent too-eager wrapping)
        self._buttons_container._threshold = total_width + 40
    
    def eventFilter(self, watched, event):
        """Update threshold when buttons are added or window resizes."""
        if event.type() == event.Type.Resize:
            self._update_threshold()
        return super().eventFilter(watched, event)


class StagedWrapLayout(QWidget):
    def __init__(self, parent=None, spacing=4):
        super().__init__(parent)
        self._spacing = spacing
        self._groups = []
        self._stay_priority = []
        self._right_align_names = set()
        self._last_row1 = []
        self._last_row2 = []
        self._last_width = -1

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(spacing)

        self._row1_widget = QWidget(self)
        self._row1_layout = QHBoxLayout(self._row1_widget)
        self._row1_layout.setContentsMargins(0, 0, 0, 0)
        self._row1_layout.setSpacing(spacing)
        self._main_layout.addWidget(self._row1_widget)

        self._row2_widget = QWidget(self)
        self._row2_layout = QHBoxLayout(self._row2_widget)
        self._row2_layout.setContentsMargins(0, 0, 0, 0)
        self._row2_layout.setSpacing(spacing)
        self._main_layout.addWidget(self._row2_widget)
        self._row2_widget.hide()

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._update_layout)

    def set_groups(self, groups, stay_priority, right_align_names=None):
        self._groups = groups
        self._stay_priority = stay_priority
        self._right_align_names = set(right_align_names or [])
        self._update_layout()

    def resizeEvent(self, a0):
        super().resizeEvent(a0)
        self._resize_timer.start(50)

    def _clear_row(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item and item.widget():
                item.widget().setParent(None)

    def _row_width(self, names, widths):
        if not names:
            return 0
        total = 0
        for name in names:
            total += widths.get(name, 0)
        total += self._spacing * (len(names) - 1)
        return total

    def _update_layout(self):
        if not self._groups:
            return

        available = self.width()
        visual_order = [name for name, _ in self._groups]
        widths = {name: widget.sizeHint().width() for name, widget in self._groups}

        keep_names = []
        for name in self._stay_priority:
            candidate = keep_names + [name]
            if available <= 0 or self._row_width(candidate, widths) <= available:
                keep_names.append(name)

        row1_names = [name for name in visual_order if name in keep_names]
        row2_names = [name for name in visual_order if name not in keep_names]

        if (
            available == self._last_width
            and row1_names == self._last_row1
            and row2_names == self._last_row2
        ):
            return

        self._last_row1 = list(row1_names)
        self._last_row2 = list(row2_names)
        self._last_width = available

        group_map = {name: widget for name, widget in self._groups}

        self._clear_row(self._row1_layout)
        row1_left = [name for name in row1_names if name not in self._right_align_names]
        row1_right = [name for name in row1_names if name in self._right_align_names]
        for name in row1_left:
            self._row1_layout.addWidget(group_map[name])
        if row1_right:
            self._row1_layout.addStretch(1)
            for name in row1_right:
                self._row1_layout.addWidget(group_map[name])

        self._clear_row(self._row2_layout)
        row2_left = [name for name in row2_names if name not in self._right_align_names]
        row2_right = [name for name in row2_names if name in self._right_align_names]
        for name in row2_left:
            self._row2_layout.addWidget(group_map[name])
        if row2_right:
            self._row2_layout.addStretch(1)
            for name in row2_right:
                self._row2_layout.addWidget(group_map[name])

        self._row2_widget.setVisible(bool(row2_names))
