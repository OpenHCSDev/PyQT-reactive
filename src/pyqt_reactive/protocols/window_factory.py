"""Window factory protocol and ABC for creating scope-aware windows.

Applications should subclass WindowFactoryABC and register it with
register_window_factory() to provide scope-specific window creation.

Example:
    class MyAppWindowFactory(WindowFactoryABC):
        def create_window_for_scope(self, scope_id: str, object_state=None):
            if scope_id == "":
                return self._create_global_config_window()
            elif "::" in scope_id:
                return self._create_step_editor_window(scope_id, object_state)
            else:
                return self._create_config_window(scope_id)

    register_window_factory(MyAppWindowFactory())
"""

from abc import ABC, abstractmethod
from typing import Protocol, Optional, Any

from PyQt6.QtWidgets import QWidget


class WindowFactoryProtocol(Protocol):
    """Protocol for creating windows for a given scope.

    Use this for duck-typed checking. For implementation, prefer WindowFactoryABC.
    """

    def create_window_for_scope(self, scope_id: str, object_state: Optional[Any] = None) -> Optional[QWidget]:
        """Create and show a window for the given scope id."""
        ...


class WindowFactoryABC(ABC):
    """Abstract base class for window factories.

    Subclass this to implement application-specific window creation logic.
    The factory is responsible for:
    - Parsing scope_id format to determine window type
    - Creating the appropriate window class
    - Showing and activating the window
    """

    @abstractmethod
    def create_window_for_scope(self, scope_id: str, object_state: Optional[Any] = None) -> Optional[QWidget]:
        """Create and show a window for the given scope_id.

        Args:
            scope_id: Scope identifier. Format is application-specific, e.g.:
                - "" (empty string): Global config
                - "/path/to/item": Item-level config
                - "/path/to/item::sub": Nested scope
            object_state: Optional ObjectState for time-travel restore

        Returns:
            The created window, or None if creation failed/skipped
        """
        ...


_window_factory: Optional[WindowFactoryProtocol] = None


def register_window_factory(factory: WindowFactoryProtocol) -> None:
    """Register a global window factory.

    Args:
        factory: Factory instance implementing WindowFactoryProtocol or WindowFactoryABC
    """
    global _window_factory
    _window_factory = factory


def get_window_factory() -> Optional[WindowFactoryProtocol]:
    """Get the registered window factory."""
    return _window_factory

