"""Generic scope-based window factory for pyqt-reactive.

Provides a registry-based system where applications register handlers
for different scope patterns. The factory dispatches to the appropriate
handler based on scope_id patterns.

Example:
    # Register a handler for a scope pattern
    ScopeWindowRegistry.register_handler(
        pattern=r"^$",  # Empty scope (global config)
        handler=create_global_config_window
    )
    
    # Create window via factory
    window = WindowFactory.create_window_for_scope(scope_id)
"""

import logging
import re
from typing import Dict, Callable, Optional, Any, List, Tuple
from PyQt6.QtWidgets import QWidget

logger = logging.getLogger(__name__)


class ScopeWindowRegistry:
    """Registry mapping scope patterns to window creation handlers.
    
    Handlers are matched in registration order (first match wins).
    """
    
    _handlers: List[Tuple[str, Callable[[str, Optional[Any]], Optional[QWidget]]]] = []
    
    @classmethod
    def register_handler(
        cls, 
        pattern: str, 
        handler: Callable[[str, Optional[Any]], Optional[QWidget]]
    ) -> None:
        """Register a handler for scopes matching the given regex pattern.
        
        Args:
            pattern: Regex pattern to match against scope_id
            handler: Callable(scope_id, object_state) -> Optional[QWidget]
        """
        cls._handlers.append((pattern, handler))
        logger.debug(f"[SCOPE_REGISTRY] Registered handler for pattern: {pattern}")
    
    @classmethod
    def unregister_handler(cls, pattern: str) -> None:
        """Remove a handler by pattern."""
        cls._handlers = [(p, h) for p, h in cls._handlers if p != pattern]
    
    @classmethod
    def clear(cls) -> None:
        """Clear all registered handlers."""
        cls._handlers.clear()
    
    @classmethod
    def find_handler(
        cls, 
        scope_id: str
    ) -> Optional[Callable[[str, Optional[Any]], Optional[QWidget]]]:
        """Find the first handler matching the scope_id."""
        for pattern, handler in cls._handlers:
            if re.match(pattern, scope_id):
                return handler
        return None


class WindowFactory:
    """Generic window factory that dispatches to registered handlers.
    
    Applications register handlers for their specific scope patterns,
    then use this factory to create windows without hardcoding domain logic.
    """
    
    @classmethod
    def create_window_for_scope(
        cls, 
        scope_id: str, 
        object_state: Optional[Any] = None
    ) -> Optional[QWidget]:
        """Create a window for the given scope_id.
        
        Dispatches to the first registered handler that matches the scope_id.
        
        Args:
            scope_id: Unique identifier for the scope/object
            object_state: Optional ObjectState instance (for time-travel scenarios)
            
        Returns:
            The created window, or None if no handler matched
        """
        handler = ScopeWindowRegistry.find_handler(scope_id)
        if handler:
            return handler(scope_id, object_state)
        
        logger.warning(f"[WINDOW_FACTORY] No handler found for scope_id: {scope_id}")
        return None
