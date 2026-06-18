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

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from objectstate import ObjectState
from PyQt6.QtWidgets import QWidget

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScopeWindowCreationRequest:
    """Typed request to materialize one ObjectState-backed UI scope."""

    scope_id: str
    object_state: ObjectState | None = None


ScopeWindowCreationHandler = Callable[[ScopeWindowCreationRequest], QWidget | None]


@dataclass(frozen=True, slots=True)
class ScopeWindowRoute:
    """One registered scope matcher and its window creation behavior."""

    pattern: str
    handler: ScopeWindowCreationHandler

    def matches(self, scope_id: str) -> bool:
        return re.match(self.pattern, scope_id) is not None

    def create_window(self, request: ScopeWindowCreationRequest) -> QWidget | None:
        return self.handler(request)


class ScopeWindowRegistry:
    """Registry mapping scope patterns to window creation handlers.
    
    Handlers are matched in registration order (first match wins).
    """
    
    _routes: list[ScopeWindowRoute] = []
    
    @classmethod
    def register_handler(
        cls,
        pattern: str,
        handler: ScopeWindowCreationHandler,
    ) -> None:
        """Register a handler for scopes matching the given regex pattern.
        
        Args:
            pattern: Regex pattern to match against scope_id
            handler: Callable(ScopeWindowCreationRequest) -> QWidget | None
        """
        cls.register_route(ScopeWindowRoute(pattern=pattern, handler=handler))

    @classmethod
    def register_route(cls, route: ScopeWindowRoute) -> None:
        """Register one nominal scope-window route."""
        cls._routes.append(route)
        logger.debug(f"[SCOPE_REGISTRY] Registered handler for pattern: {route.pattern}")
    
    @classmethod
    def unregister_handler(cls, pattern: str) -> None:
        """Remove a handler by pattern."""
        cls._routes = [route for route in cls._routes if route.pattern != pattern]
    
    @classmethod
    def clear(cls) -> None:
        """Clear all registered handlers."""
        cls._routes.clear()
    
    @classmethod
    def find_handler(
        cls,
        scope_id: str,
    ) -> ScopeWindowRoute | None:
        """Find the first route matching the scope_id."""
        for route in cls._routes:
            if route.matches(scope_id):
                return route
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
        object_state: ObjectState | None = None,
    ) -> QWidget | None:
        """Create a window for the given scope_id.
        
        Dispatches to the first registered handler that matches the scope_id.
        
        Args:
            scope_id: Unique identifier for the scope/object
            object_state: Optional ObjectState instance (for time-travel scenarios)
            
        Returns:
            The created window, or None if no handler matched
        """
        route = ScopeWindowRegistry.find_handler(scope_id)
        if route is not None:
            return route.create_window(
                ScopeWindowCreationRequest(
                    scope_id=scope_id,
                    object_state=object_state,
                )
            )
        
        logger.warning(f"[WINDOW_FACTORY] No handler found for scope_id: {scope_id}")
        return None
