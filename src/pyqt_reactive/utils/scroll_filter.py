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

    def __init__(self, scroll_speed_multiplier: float = 3.0):
        """Initialize the filter.
        
        Args:
            scroll_speed_multiplier: Multiplier for scroll speed (default: 3.0)
        """
        super().__init__()
        self._multiplier = scroll_speed_multiplier

    def eventFilter(self, obj, event):
        """Filter wheel events for horizontal scrolling.
        
        Args:
            obj: The object receiving the event
            event: The event to filter
            
        Returns:
            True if the event was handled, False to pass it through
        """
        if event.type() == QEvent.Type.Wheel:
            # Check if Shift is pressed
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                # Find the scroll area this event belongs to
                scroll_area = None
                parent = obj
                while parent is not None:
                    if isinstance(parent, QAbstractScrollArea):
                        scroll_area = parent
                        break
                    parent = parent.parent()

                if scroll_area is not None:
                    h_scrollbar = scroll_area.horizontalScrollBar()
                    if h_scrollbar is not None and h_scrollbar.isVisible():
                        delta = event.angleDelta().y()
                        if delta != 0:
                            step = h_scrollbar.singleStep() * self._multiplier
                            h_scrollbar.setValue(h_scrollbar.value() - int(delta / 120) * step)
                            event.accept()
                            return True
        
        # Pass event through to next filter
        return super().eventFilter(obj, event)


def install_shift_wheel_scrolling(app, scroll_speed_multiplier: float = 3.0) -> ShiftWheelHorizontalScrollFilter:
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
