"""
TearOffRegistry - Global registry for tear-off tab drag operations.

Tracks the current drag operation and all tear-off capable widgets
for cross-window drag-and-drop support.
"""

import logging
from typing import Optional, List, TYPE_CHECKING
from PyQt6.QtCore import QObject, QPoint
from PyQt6.QtWidgets import QApplication

if TYPE_CHECKING:
    from .tear_off_tab_widget import TearOffTabWidget, FloatingTabWindow, TabDragData

logger = logging.getLogger(__name__)


class TearOffRegistry(QObject):
    """
    Singleton registry for tear-off tab operations.
    
    Tracks:
    - Current drag operation (tab being dragged)
    - All tear-off capable widgets (potential drop targets)
    - Floating windows (current drag sources)
    
    This enables dragging tabs between different windows.
    """
    
    _instance: Optional['TearOffRegistry'] = None
    
    def __init__(self):
        super().__init__()
        self._current_drag: Optional['TabDragData'] = None
        self._floating_window: Optional['FloatingTabWindow'] = None
        self._targets: List['TearOffTabWidget'] = []
        self._current_hover_target: Optional['TearOffTabWidget'] = None
        
    @classmethod
    def instance(cls) -> 'TearOffRegistry':
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def register_drag(cls, drag_data: 'TabDragData', 
                      floating_window: 'FloatingTabWindow'):
        """Register a new drag operation."""
        registry = cls.instance()
        registry._current_drag = drag_data
        registry._floating_window = floating_window
        logger.debug(f"Registered drag for tab: {drag_data.tab_text}")
        
    @classmethod
    def clear_drag(cls):
        """Clear current drag operation."""
        registry = cls.instance()
        registry._current_drag = None
        registry._floating_window = None
        registry._current_hover_target = None
        logger.debug("Cleared drag")
        
    @classmethod
    def get_current_drag(cls) -> Optional['TabDragData']:
        """Get current drag data."""
        return cls.instance()._current_drag
    
    @classmethod
    def register_target(cls, target: 'TearOffTabWidget'):
        """Register a widget as a potential drop target."""
        registry = cls.instance()
        if target not in registry._targets:
            registry._targets.append(target)
            logger.debug(f"Registered tear-off target: {target}")
            
    @classmethod
    def unregister_target(cls, target: 'TearOffTabWidget'):
        """Unregister a drop target."""
        registry = cls.instance()
        if target in registry._targets:
            registry._targets.remove(target)
            logger.debug(f"Unregistered tear-off target: {target}")
            
    @classmethod
    def check_hover(cls, floating_window: 'FloatingTabWindow', global_pos: QPoint):
        """
        Check if floating window is hovering over a drop target.
        
        Called continuously during drag to update visual feedback.
        """
        registry = cls.instance()
        
        # Find widget under cursor
        widget = QApplication.widgetAt(global_pos)
        if not widget:
            # Clear hover if we were hovering
            if registry._current_hover_target:
                registry._current_hover_target._hide_drop_indicator()
                registry._current_hover_target = None
            return
            
        # Find TearOffTabWidget ancestor
        target = None
        temp = widget
        while temp:
            if hasattr(temp, '_is_tear_off_tab_widget'):
                target = temp
                break
            temp = temp.parent()
            
        # Update hover state
        if target != registry._current_hover_target:
            # Clear old hover
            if registry._current_hover_target:
                registry._current_hover_target._hide_drop_indicator()
                
            # Set new hover
            registry._current_hover_target = target
            if target:
                # Convert global pos to target local pos
                local_pos = target.mapFromGlobal(global_pos)
                target._show_drop_indicator(local_pos)
                
    @classmethod
    def get_drop_target(cls, floating_window: 'FloatingTabWindow') \
            -> Optional['TearOffTabWidget']:
        """Get the current drop target (if any)."""
        registry = cls.instance()
        return registry._current_hover_target
    
    @classmethod
    def perform_drop(cls, floating_window: 'FloatingTabWindow', 
                     target: 'TearOffTabWidget'):
        """
        Perform the drop operation.
        
        This simulates a drop event on the target widget.
        """
        registry = cls.instance()
        drag_data = registry._current_drag
        
        if not drag_data:
            logger.warning("No drag data for drop")
            return
            
        # Hide drop indicator
        target._hide_drop_indicator()
        
        # Get drop position
        # Since we're not in a real drop event, use center of target
        local_pos = target.rect().center()
        
        # Calculate drop index
        drop_index = target._calculate_drop_index(local_pos)
        
        # Add tab to target
        tab_widget = drag_data.tab_widget
        tab_text = drag_data.tab_text
        
        # Re-parent
        tab_widget.setParent(None)
        new_index = target.insertTab(drop_index, tab_widget, tab_text)
        target.setCurrentIndex(new_index)
        
        # Clear state
        registry._current_drag = None
        registry._floating_window = None
        registry._current_hover_target = None
        
        # Emit signals
        target.tab_docked.emit(tab_widget, tab_text, new_index)
        if target.on_tab_docked:
            target.on_tab_docked(tab_widget, tab_text, new_index)
            
        logger.debug(f"Dropped tab at index {new_index}: {tab_text}")
