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
ScopeWindowScopeResolver = Callable[[str], str]
ScopeWindowFieldPathResolver = Callable[[str, str | None], str | None]
ScopeWindowItemIdResolver = Callable[[str, str | None], str | None]


def _identity_scope(scope_id: str) -> str:
    return scope_id


def _identity_field_path(scope_id: str, field_path: str | None) -> str | None:
    del scope_id
    return field_path


def _identity_item_id(scope_id: str, item_id: str | None) -> str | None:
    del scope_id
    return item_id


@dataclass(frozen=True, slots=True)
class ScopeWindowNavigationTarget:
    """Resolved WindowManager target for one requested ObjectState scope."""

    requested_scope_id: str
    window_scope_id: str
    item_id: str | None
    field_path: str | None


@dataclass(frozen=True, slots=True)
class ScopeWindowRoute:
    """One registered scope matcher and its window creation behavior."""

    pattern: str
    handler: ScopeWindowCreationHandler | None = None
    window_scope_resolver: ScopeWindowScopeResolver = _identity_scope
    field_path_resolver: ScopeWindowFieldPathResolver = _identity_field_path
    item_id_resolver: ScopeWindowItemIdResolver = _identity_item_id

    def matches(self, scope_id: str) -> bool:
        return re.match(self.pattern, scope_id) is not None

    def create_window(self, request: ScopeWindowCreationRequest) -> QWidget | None:
        if self.handler is None:
            return None
        return self.handler(request)

    def navigation_target(
        self,
        scope_id: str,
        *,
        item_id: str | None = None,
        field_path: str | None = None,
    ) -> ScopeWindowNavigationTarget:
        return ScopeWindowNavigationTarget(
            requested_scope_id=scope_id,
            window_scope_id=self.window_scope_resolver(scope_id),
            item_id=self.item_id_resolver(scope_id, item_id),
            field_path=self.field_path_resolver(scope_id, field_path),
        )


class ScopeWindowRegistry:
    """Registry mapping scope patterns to window creation handlers.
    
    Handlers are matched in registration order (first match wins).
    """
    
    _routes: list[ScopeWindowRoute] = []
    
    @classmethod
    def register_handler(
        cls,
        pattern: str,
        handler: ScopeWindowCreationHandler | None = None,
        *,
        window_scope_resolver: ScopeWindowScopeResolver = _identity_scope,
        field_path_resolver: ScopeWindowFieldPathResolver = _identity_field_path,
        item_id_resolver: ScopeWindowItemIdResolver = _identity_item_id,
    ) -> None:
        """Register a handler for scopes matching the given regex pattern.
        
        Args:
            pattern: Regex pattern to match against scope_id
            handler: Callable(ScopeWindowCreationRequest) -> QWidget | None
        """
        cls.register_route(
            ScopeWindowRoute(
                pattern=pattern,
                handler=handler,
                window_scope_resolver=window_scope_resolver,
                field_path_resolver=field_path_resolver,
                item_id_resolver=item_id_resolver,
            )
        )

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
