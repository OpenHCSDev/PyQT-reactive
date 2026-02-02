"""Global event filter for Shift+Wheel horizontal scrolling.

This module provides a global event filter that enables Shift+MouseWheel
to scroll horizontally in all QAbstractScrollArea widgets.

Usage:
    from pyqt_reactive.utils.scroll_filter import install_shift_wheel_scrolling
    
    # In your application initialization:
    install_shift_wheel_scrolling(app)
"""

from PyQt6.QtWidgets import QAbstractScrollArea
from PyQt6.QtCore import QObject, QEvent, Qt
from weakref import WeakKeyDictionary
import math


class ShiftWheelHorizontalScrollFilter(QObject):
    """Global event filter that enables Shift+Wheel horizontal scrolling.
    
    This filter intercepts wheel events across the entire application. When
    Shift is held and the mouse wheel is scrolled, it scrolls the horizontal
    scrollbar of the QAbstractScrollArea under the cursor (if visible).
    
    Example:
        app = QApplication(sys.argv)
        filter = ShiftWheelHorizontalScrollFilter()
        app.installEventFilter(filter)
    """

    def __init__(self, scroll_speed_multiplier: float = 0.01):
        """Initialize the filter.
        
        Args:
            scroll_speed_multiplier: Multiplier for scroll speed (default: 3.0)
        """
        super().__init__()
        self._multiplier = scroll_speed_multiplier
        # Accumulators store fractional scroll amounts per-horizontal-scrollbar
        # so small wheel movements produce smooth scrolling once accumulated.
        self._accumulators: "WeakKeyDictionary[object, float]" = WeakKeyDictionary()

    def eventFilter(self, a0, a1):
        """Filter wheel events for horizontal scrolling.
        
        Args:
            obj: The object receiving the event
            event: The event to filter
            
        Returns:
            True if the event was handled, False to pass it through
        """
        if a1.type() == QEvent.Type.Wheel:
            # Check if Shift is pressed
            if a1.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                # Find the scroll area this event belongs to
                scroll_area = None
                parent = a0
                while parent is not None:
                    if isinstance(parent, QAbstractScrollArea):
                        scroll_area = parent
                        break
                    parent = parent.parent()

                if scroll_area is not None:
                    h_scrollbar = scroll_area.horizontalScrollBar()
                    if h_scrollbar is not None and h_scrollbar.isVisible():
                        delta = a1.angleDelta().y()
                        if delta != 0:
                            # Use singleStep as base; fall back to 1 if it's 0
                            base_step = h_scrollbar.singleStep() or 1
                            step_float = base_step * self._multiplier

                            # Convert wheel delta to fractional steps (larger denominator = less sensitive)
                            delta_steps_float = float(delta) / 240.0

                            # Desired movement (may be fractional)
                            movement = delta_steps_float * step_float

                            # Accumulate fractional movement for this scrollbar
                            acc = self._accumulators.get(h_scrollbar, 0.0) + movement

                            # Determine integer movement to apply now using truncation toward zero
                            # (requires |acc| >= 1.0 before any movement occurs)
                            apply_steps = int(acc)
                            if apply_steps != 0:
                                new_value = h_scrollbar.value() - apply_steps
                                h_scrollbar.setValue(int(new_value))
                                # Remove applied integer part from accumulator
                                acc -= apply_steps

                            # Store back accumulator (keep fractional remainder)
                            # Clamp accumulator to a reasonable range to avoid runaway
                            max_acc = step_float * 20
                            if acc > max_acc:
                                acc = max_acc
                            elif acc < -max_acc:
                                acc = -max_acc

                            self._accumulators[h_scrollbar] = acc
                            a1.accept()
                            return True
        
        # Pass event through to next filter
        return super().eventFilter(a0, a1)


def install_shift_wheel_scrolling(app, scroll_speed_multiplier: float = 0.01) -> ShiftWheelHorizontalScrollFilter:
    """Install global Shift+Wheel horizontal scrolling for the application.
    
    This is a convenience function that creates and installs the event filter
    on the QApplication instance.
    
    Args:
        app: The QApplication instance
        scroll_speed_multiplier: Multiplier for scroll speed (default: 3.0)
        
    Returns:
        The installed filter instance (keep a reference to prevent GC)
        
    Example:
        import sys
        from PyQt6.QtWidgets import QApplication
        from pyqt_reactive.utils.scroll_filter import install_shift_wheel_scrolling
        
        app = QApplication(sys.argv)
        scroll_filter = install_shift_wheel_scrolling(app)
        # Keep scroll_filter reference alive for the lifetime of the app
        
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    """
    filter_obj = ShiftWheelHorizontalScrollFilter(scroll_speed_multiplier)
    app.installEventFilter(filter_obj)
    return filter_obj
