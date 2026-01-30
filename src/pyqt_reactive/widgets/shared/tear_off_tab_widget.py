"""
TearOffTabWidget - Chrome-style detachable tabs for PyQt6.

Allows users to drag tabs out to create floating windows,
and drag them into other windows to dock them.
"""

import logging
from typing import Optional, List, Callable
from PyQt6.QtWidgets import (
    QTabWidget, QTabBar, QWidget, QVBoxLayout, QDialog,
    QApplication, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData, QPoint, QRect
from PyQt6.QtGui import QDrag, QPixmap, QPainter, QColor, QCursor

logger = logging.getLogger(__name__)


class TabDragData:
    """Data container for tab drag operations."""
    
    def __init__(self, source_widget: 'TearOffTabWidget', tab_index: int, 
                 tab_text: str, tab_widget: QWidget):
        self.source_widget = source_widget
        self.tab_index = tab_index
        self.tab_text = tab_text
        self.tab_widget = tab_widget
        self.drag_start_pos: Optional[QPoint] = None


class TearOffTabBar(QTabBar):
    """Custom tab bar that supports tear-off drag operations."""
    
    # Signal emitted when a tab should be torn off
    tab_tear_off_requested = pyqtSignal(int, QPoint)  # tab_index, global_pos
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_start_pos: Optional[QPoint] = None
        self._tear_off_threshold = 30  # pixels to drag before tearing off
        self.setMovable(True)
        
    def mousePressEvent(self, event):
        """Track initial click position for drag detection."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)
        
    def mouseMoveEvent(self, event):
        """Detect drag-out for tear-off."""
        if not self._drag_start_pos:
            super().mouseMoveEvent(event)
            return
            
        # Calculate drag distance
        drag_distance = (event.pos() - self._drag_start_pos).manhattanLength()
        
        # Check if dragged outside tab bar bounds (vertical tear-off)
        tab_rect = self.rect()
        pos_in_bar = event.pos()
        
        outside_vertically = pos_in_bar.y() < -self._tear_off_threshold or \
                           pos_in_bar.y() > tab_rect.height() + self._tear_off_threshold
        outside_horizontally = pos_in_bar.x() < -self._tear_off_threshold or \
                             pos_in_bar.x() > tab_rect.width() + self._tear_off_threshold
        
        # If dragged far enough outside tab bar, initiate tear-off
        if (outside_vertically or outside_horizontally) and drag_distance > self._tear_off_threshold:
            tab_index = self.tabAt(self._drag_start_pos)
            if tab_index >= 0:
                global_pos = self.mapToGlobal(event.pos())
                self.tab_tear_off_requested.emit(tab_index, global_pos)
                self._drag_start_pos = None
                return
                
        super().mouseMoveEvent(event)
        
    def mouseReleaseEvent(self, event):
        """Reset drag tracking."""
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)


class TearOffTabWidget(QTabWidget):
    """
    QTabWidget with Chrome-style tear-off tab support.
    
    Allows dragging tabs out to create floating windows,
    and dragging them into other TearOffTabWidgets to dock.
    
    Features:
    - Drag tab out to create floating window
    - Drag tab into another TearOffTabWidget to dock
    - Visual feedback during drag (preview pixmap)
    - Automatic cleanup of empty floating windows
    
    Usage:
        tab_widget = TearOffTabWidget()
        tab_widget.addTab(widget, "Tab 1")
        tab_widget.addTab(widget2, "Tab 2")
        
        # Optional: Set callback when tab is torn off
        tab_widget.on_tab_torn_off = lambda tab_widget, tab_text: print(f"Torn off: {tab_text}")
    """
    
    # Signals
    tab_torn_off = pyqtSignal(QWidget, str)  # tab_widget, tab_text
    tab_docked = pyqtSignal(QWidget, str, int)  # tab_widget, tab_text, index
    
    def __init__(self, parent=None):
        super().__init__(parent)

        # Marker for TearOffRegistry to identify tear-off capable widgets
        self._is_tear_off_tab_widget = True

        # Replace default tab bar with tear-off capable one
        self._tear_off_bar = TearOffTabBar(self)
        self._tear_off_bar.tab_tear_off_requested.connect(self._on_tear_off_requested)
        self.setTabBar(self._tear_off_bar)

        # Accept drops from other tear-off tabs
        self.setAcceptDrops(True)

        # Drag state
        self._current_drag: Optional[TabDragData] = None
        self._floating_window: Optional['FloatingTabWindow'] = None

        # Callbacks
        self.on_tab_torn_off: Optional[Callable[[QWidget, str], None]] = None
        self.on_tab_docked: Optional[Callable[[QWidget, str, int], None]] = None

        # Visual feedback
        self._drop_indicator: Optional[QFrame] = None

        # Register with TearOffRegistry
        from pyqt_reactive.widgets.shared.tear_off_registry import TearOffRegistry
        TearOffRegistry.register_target(self)

    def _on_tear_off_requested(self, tab_index: int, global_pos: QPoint):
        """Handle tear-off request from tab bar."""
        logger.debug(f"Tear off requested for tab {tab_index}")
        
        if tab_index < 0 or tab_index >= self.count():
            return
            
        # Get tab info
        tab_text = self.tabText(tab_index)
        tab_widget = self.widget(tab_index)
        
        if not tab_widget:
            return
            
        # Create drag data
        self._current_drag = TabDragData(self, tab_index, tab_text, tab_widget)
        
        # Remove tab from this widget (but don't delete)
        self.removeTab(tab_index)
        
        # Create floating window
        self._create_floating_window(tab_widget, tab_text, global_pos)
        
        # Emit signal
        self.tab_torn_off.emit(tab_widget, tab_text)
        if self.on_tab_torn_off:
            self.on_tab_torn_off(tab_widget, tab_text)
            
    def _create_floating_window(self, tab_widget: QWidget, tab_text: str, 
                                global_pos: QPoint):
        """Create floating window with tab content."""
        from pyqt_reactive.widgets.shared.tear_off_registry import TearOffRegistry
        
        self._floating_window = FloatingTabWindow(tab_widget, tab_text, self)
        
        # Position near cursor
        self._floating_window.move(global_pos - QPoint(50, 20))
        self._floating_window.show()
        
        # Register with registry for drop detection
        TearOffRegistry.register_drag(self._current_drag, self._floating_window)
        
        logger.debug(f"Created floating window for tab: {tab_text}")
        
    def dragEnterEvent(self, event):
        """Accept drag from other tear-off tabs."""
        from pyqt_reactive.widgets.shared.tear_off_registry import TearOffRegistry
        
        drag_data = TearOffRegistry.get_current_drag()
        if drag_data and drag_data.source_widget != self:
            event.acceptProposedAction()
            self._show_drop_indicator(event.pos())
            logger.debug("Drag enter accepted")
        else:
            event.ignore()
            
    def dragMoveEvent(self, event):
        """Update drop indicator position."""
        from pyqt_reactive.widgets.shared.tear_off_registry import TearOffRegistry
        
        drag_data = TearOffRegistry.get_current_drag()
        if drag_data and drag_data.source_widget != self:
            event.acceptProposedAction()
            self._update_drop_indicator(event.pos())
        else:
            event.ignore()
            
    def dragLeaveEvent(self, event):
        """Hide drop indicator."""
        self._hide_drop_indicator()
        
    def dropEvent(self, event):
        """Handle tab drop from another window."""
        from pyqt_reactive.widgets.shared.tear_off_registry import TearOffRegistry
        
        self._hide_drop_indicator()
        
        drag_data = TearOffRegistry.get_current_drag()
        if not drag_data or drag_data.source_widget == self:
            event.ignore()
            return
            
        # Get drop position
        drop_index = self._calculate_drop_index(event.pos())
        
        # Close floating window
        if drag_data.source_widget._floating_window:
            drag_data.source_widget._floating_window.close()
            drag_data.source_widget._floating_window = None
            
        # Add tab to this widget
        tab_widget = drag_data.tab_widget
        tab_text = drag_data.tab_text
        
        # Re-parent the widget
        tab_widget.setParent(None)
        new_index = self.insertTab(drop_index, tab_widget, tab_text)
        self.setCurrentIndex(new_index)
        
        # Clear drag data
        TearOffRegistry.clear_drag()
        drag_data.source_widget._current_drag = None
        
        # Emit signals
        self.tab_docked.emit(tab_widget, tab_text, new_index)
        if self.on_tab_docked:
            self.on_tab_docked(tab_widget, tab_text, new_index)
            
        event.acceptProposedAction()
        logger.debug(f"Tab dropped at index {new_index}: {tab_text}")
        
    def _calculate_drop_index(self, pos: QPoint) -> int:
        """Calculate which tab index to drop at based on mouse position."""
        # Find which tab the mouse is over
        for i in range(self.count()):
            tab_rect = self.tabBar().tabRect(i)
            if tab_rect.contains(pos):
                # Drop before this tab
                return i
                
        # Drop at end
        return self.count()
        
    def _show_drop_indicator(self, pos: QPoint):
        """Show visual indicator for drop position."""
        if not self._drop_indicator:
            self._drop_indicator = QFrame(self)
            self._drop_indicator.setStyleSheet("background-color: #0078d4;")
            self._drop_indicator.setFixedWidth(3)
            
        drop_index = self._calculate_drop_index(pos)
        
        if drop_index < self.count():
            # Show indicator before this tab
            tab_rect = self.tabBar().tabRect(drop_index)
            self._drop_indicator.setGeometry(tab_rect.left() - 2, tab_rect.top(), 3, tab_rect.height())
        else:
            # Show indicator at end
            if self.count() > 0:
                last_rect = self.tabBar().tabRect(self.count() - 1)
                self._drop_indicator.setGeometry(last_rect.right() + 1, last_rect.top(), 3, last_rect.height())
            else:
                self._drop_indicator.setGeometry(0, 0, 3, self.tabBar().height())
                
        self._drop_indicator.show()
        self._drop_indicator.raise_()
        
    def _update_drop_indicator(self, pos: QPoint):
        """Update drop indicator position during drag."""
        self._show_drop_indicator(pos)
        
    def _hide_drop_indicator(self):
        """Hide drop indicator."""
        if self._drop_indicator:
            self._drop_indicator.hide()

    def closeEvent(self, event):
        """Unregister from registry when closed."""
        from pyqt_reactive.widgets.shared.tear_off_registry import TearOffRegistry
        TearOffRegistry.unregister_target(self)
        super().closeEvent(event)


class FloatingTabWindow(QDialog):
    """
    Floating window for torn-off tabs.
    
    Contains a single tab's content and can be dragged
    to dock into other TearOffTabWidgets.
    """
    
    def __init__(self, content_widget: QWidget, title: str, 
                 source_tab_widget: TearOffTabWidget, parent=None):
        super().__init__(parent)
        
        self.source_tab_widget = source_tab_widget
        self.content_widget = content_widget
        self.title = title
        
        # Window settings
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.resize(800, 600)
        
        # Setup UI
        self._setup_ui()
        
        # Track dragging for docking
        self._is_dragging = False
        self._drag_start_pos: Optional[QPoint] = None
        
    def _setup_ui(self):
        """Setup the floating window UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Add content widget
        layout.addWidget(self.content_widget)
        
    def mousePressEvent(self, event):
        """Start tracking for window drag."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.globalPos()
            self._is_dragging = False
        super().mousePressEvent(event)
        
    def mouseMoveEvent(self, event):
        """Handle window dragging and check for dock targets."""
        from pyqt_reactive.widgets.shared.tear_off_registry import TearOffRegistry
        
        if self._drag_start_pos and event.buttons() == Qt.MouseButton.LeftButton:
            # Check if actually dragging (moved enough)
            if not self._is_dragging:
                distance = (event.globalPos() - self._drag_start_pos).manhattanLength()
                if distance > 10:
                    self._is_dragging = True
                    
            if self._is_dragging:
                # Move window
                delta = event.globalPos() - self._drag_start_pos
                self.move(self.pos() + delta)
                self._drag_start_pos = event.globalPos()
                
                # Check if over a dock target
                TearOffRegistry.check_hover(self, event.globalPos())
                
        super().mouseMoveEvent(event)
        
    def mouseReleaseEvent(self, event):
        """Handle drop - dock if over a target."""
        from pyqt_reactive.widgets.shared.tear_off_registry import TearOffRegistry
        
        if self._is_dragging and event.button() == Qt.MouseButton.LeftButton:
            # Check if we should dock
            target = TearOffRegistry.get_drop_target(self)
            if target:
                logger.debug(f"Docking into target: {target}")
                # The drop logic is handled by the target's dropEvent
                # We just need to trigger it
                TearOffRegistry.perform_drop(self, target)
            else:
                logger.debug("No dock target found, keeping window floating")
                
        self._drag_start_pos = None
        self._is_dragging = False
        super().mouseReleaseEvent(event)
        
    def closeEvent(self, event):
        """Handle window close - return tab to source if not docked."""
        from pyqt_reactive.widgets.shared.tear_off_registry import TearOffRegistry
        
        # Check if this is a clean close (not docking)
        drag_data = TearOffRegistry.get_current_drag()
        if drag_data and drag_data.source_widget == self.source_tab_widget:
            # Window closed without docking - re-add to source
            logger.debug("Floating window closed, returning tab to source")
            drag_data.source_widget.addTab(drag_data.tab_widget, drag_data.tab_text)
            TearOffRegistry.clear_drag()
            self.source_tab_widget._current_drag = None
            
        super().closeEvent(event)
