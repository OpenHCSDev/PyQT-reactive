"""Global window registry for scoped singleton windows with navigation support.

Ensures only one window per scope_id exists at a time and provides navigation
API for inheritance tracking (click field → open window + scroll to source).

Architecture:
- Centralized registry (like ObjectStateRegistry pattern)
- Singleton windows per scope_id
- Extensible navigation protocol
- Auto-cleanup on window close
- Fail-loud if window deleted but still in registry

Example Usage:

    # Basic: Show or focus existing window
    WindowManager.show_or_focus(
        scope_id="plate1",
        window_factory=lambda: ConfigWindow(...)
    )

    # Future: Navigate to specific field for inheritance tracking
    WindowManager.focus_and_navigate(
        scope_id="plate1",
        field_path="well_filter_config.well_filter"  # Scroll to this field
    )
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Dict, Callable, Optional
from PyQt6 import sip
from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QCursor, QGuiApplication
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtCore import QTimer

from pyqt_reactive.services.window_navigation import (
    NullWindowNavigationDriver,
    RegisteredWindowNavigationRequest,
    WindowNavigationDriver,
)

if TYPE_CHECKING:
    from pyqt_reactive.services.window_code_document import WindowCodeDocumentDriver

logger = logging.getLogger(__name__)


class WindowLookupStatus(Enum):
    PRESENT = "present"
    MISSING = "missing"
    HIDDEN = "hidden"
    STALE = "stale"


@dataclass(frozen=True)
class WindowLookupResult:
    scope_id: str
    status: WindowLookupStatus
    window: Optional[QWidget] = None

    @property
    def is_present(self) -> bool:
        return self.status is WindowLookupStatus.PRESENT and self.window is not None


class NavigationRetryScheduler:
    """Schedule bounded navigation retries while forms/lists finish building."""

    MAX_RETRIES = 10
    RETRY_DELAY_MS = 50

    @classmethod
    def schedule(
        cls,
        request: RegisteredWindowNavigationRequest,
        driver: WindowNavigationDriver,
        retry_counts: Dict[int, int],
        check_and_navigate: Callable[[], None],
    ) -> bool:
        window_key = id(request.window)
        current_retry_count = cls._retry_count(window_key, retry_counts)
        if current_retry_count >= cls.MAX_RETRIES:
            logger.warning("[WINDOW_MGR] Max retries reached for navigation")
            return False

        next_retry_count = current_retry_count + 1
        retry_counts[window_key] = next_retry_count
        logger.debug(
            "[WINDOW_MGR] Scheduling navigation retry attempt %s",
            next_retry_count,
        )

        if cls._register_build_callback(driver, check_and_navigate):
            return True

        QTimer.singleShot(cls.RETRY_DELAY_MS, check_and_navigate)
        return True

    @staticmethod
    def clear(
        request: RegisteredWindowNavigationRequest,
        retry_counts: Dict[int, int],
    ) -> None:
        window_key = id(request.window)
        if window_key in retry_counts:
            del retry_counts[window_key]

    @staticmethod
    def _retry_count(window_key: int, retry_counts: Dict[int, int]) -> int:
        if window_key in retry_counts:
            return retry_counts[window_key]
        return 0

    @classmethod
    def _register_build_callback(
        cls,
        driver: WindowNavigationDriver,
        check_and_navigate: Callable[[], None],
    ) -> bool:
        callback_lists = driver.build_complete_callbacks()
        if len(callback_lists) == 0:
            return False

        def retry_after_build() -> None:
            QTimer.singleShot(cls.RETRY_DELAY_MS, check_and_navigate)

        registered = False
        for callbacks in callback_lists:
            if len(callbacks) == 0:
                continue
            callbacks.append(retry_after_build)
            registered = True
        return registered


class WindowManager:
    """Global registry for scoped windows with navigation support.

    Ensures only one window per scope_id exists at a time.
    Provides navigation API for focusing windows and scrolling to items/fields.

    Patterns:
    - Singleton windows per scope (like ObjectStateRegistry for states)
    - Navigation protocol (optional methods, duck typing)
    - Auto-cleanup on close (no manual unregistration needed)
    - Fail-loud on stale references
    """

    # Global registry of open windows by scope_id
    _scoped_windows: Dict[str, QWidget] = {}
    _navigation_drivers: Dict[str, WindowNavigationDriver] = {}
    _code_document_drivers: Dict[str, "WindowCodeDocumentDriver"] = {}
    _navigation_retry_counts: Dict[int, int] = {}

    @classmethod
    def _resolve_registered_window(
        cls,
        scope_id: str,
        *,
        require_visible: bool = False,
    ) -> WindowLookupResult:
        if scope_id not in cls._scoped_windows:
            return WindowLookupResult(scope_id, WindowLookupStatus.MISSING)
        window = cls._scoped_windows[scope_id]

        if sip.isdeleted(window):
            result = WindowLookupResult(scope_id, WindowLookupStatus.STALE)
            cls._drop_resolved_window(result)
            return result

        visible = window.isVisible()
        if require_visible and not visible:
            cls.unregister(scope_id)
            return WindowLookupResult(scope_id, WindowLookupStatus.HIDDEN)

        return WindowLookupResult(scope_id, WindowLookupStatus.PRESENT, window)

    @classmethod
    def _drop_resolved_window(cls, result: WindowLookupResult) -> None:
        if result.status is WindowLookupStatus.STALE:
            cls.unregister(result.scope_id)

    @classmethod
    def _navigation_driver(cls, scope_id: str) -> WindowNavigationDriver:
        if scope_id in cls._navigation_drivers:
            return cls._navigation_drivers[scope_id]
        return NullWindowNavigationDriver()

    @classmethod
    def position_window_near_cursor(
        cls,
        window: QWidget,
        offset: int = 0,
        avoid_widgets: Sequence[QWidget] = (),
    ) -> None:
        """Place window centered on mouse cursor without overlapping floating windows."""
        resolved_avoid_widgets = tuple(avoid_widgets)
        cursor_pos = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor_pos)
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return

        available = screen.availableGeometry()
        size = window.size()
        if size.isEmpty():
            size = window.sizeHint()
        width = size.width()
        height = size.height()

        bounds_left = available.left()
        bounds_top = available.top()
        bounds_right = bounds_left + available.width()
        bounds_bottom = bounds_top + available.height()

        base_x = cursor_pos.x() - (width // 2) + offset
        base_y = cursor_pos.y() - (height // 2) + offset

        def clamp(x: int, y: int) -> tuple[int, int]:
            return (
                min(max(x, bounds_left), bounds_right - width),
                min(max(y, bounds_top), bounds_bottom - height),
            )

        avoid_rects = []
        for widget in resolved_avoid_widgets:
            try:
                avoid_rects.append(widget.frameGeometry())
            except RuntimeError:
                continue

        def intersects_any(rect: QRect) -> bool:
            for widget in QApplication.topLevelWidgets():
                if widget is window:
                    continue
                if not widget.isVisible():
                    continue
                if isinstance(widget, QMainWindow):
                    continue
                try:
                    other = widget.frameGeometry()
                except RuntimeError:
                    continue
                if rect.intersects(other):
                    return True
            for other in avoid_rects:
                if rect.intersects(other):
                    return True
            return False

        candidates: list[tuple[int, int]] = []
        gap = 12
        for avoid in avoid_rects:
            if avoid.contains(cursor_pos):
                candidates.extend(
                    [
                        (avoid.right() + gap, cursor_pos.y() - (height // 2)),
                        (avoid.left() - width - gap, cursor_pos.y() - (height // 2)),
                        (cursor_pos.x() - (width // 2), avoid.bottom() + gap),
                        (cursor_pos.x() - (width // 2), avoid.top() - height - gap),
                    ]
                )
                break

        if len(candidates) == 0:
            candidates.append((base_x, base_y))

        step = 32
        rings = 12
        for r in range(1, rings + 1):
            delta = r * step
            candidates.extend(
                [
                    (base_x + delta, base_y),
                    (base_x - delta, base_y),
                    (base_x, base_y + delta),
                    (base_x, base_y - delta),
                    (base_x + delta, base_y + delta),
                    (base_x + delta, base_y - delta),
                    (base_x - delta, base_y + delta),
                    (base_x - delta, base_y - delta),
                ]
            )

        for candidate_x, candidate_y in candidates:
            x, y = clamp(candidate_x, candidate_y)
            rect = QRect(x, y, width, height)
            if not intersects_any(rect):
                window.move(x, y)
                return

        x, y = clamp(base_x, base_y)
        window.move(x, y)

    @classmethod
    def _focus_window(cls, window: QWidget, scope_id: str) -> None:
        """Show, raise, activate, and restore a registered window."""
        if not window.isVisible():
            window.show()

        app = QApplication.instance()
        is_already_active = app is not None and app.activeWindow() == window
        if is_already_active:
            logger.debug(
                "[WINDOW_MGR] Window already active, skipping raise/activate: %s",
                scope_id,
            )
        else:
            window.raise_()
            window.activateWindow()

        if window.isMinimized():
            window.showNormal()

    @classmethod
    def show_or_focus(
        cls,
        scope_id: str,
        window_factory: Callable[[], QWidget],
        item_id: Optional[str] = None,
        field_path: Optional[str] = None,
        navigation_driver: WindowNavigationDriver | None = None,
        code_document_driver: "WindowCodeDocumentDriver | None" = None,
    ) -> QWidget:
        """Show window for scope_id. Reuse existing or create new.

        If window already exists for this scope_id, brings it to front.
        Otherwise, creates new window using factory and registers it.

        Auto-cleanup: Window is automatically unregistered when closed.

        IMPORTANT: Navigation is deferred to handle async widget creation.
        The scroll/flash only triggers after:
        1. Window is shown and painted
        2. Target widgets are built (via _on_build_complete_callbacks)

        Args:
            scope_id: Unique identifier for the window (e.g., plate path, step scope)
            window_factory: Callable that creates the window if needed
            item_id: Optional item to select after showing (e.g., list index)
            field_path: Optional field to highlight after showing (e.g., "well_filter_config.well_filter")

        Returns:
            The window (existing or newly created)

        Example:
            def create_config_window():
                return ConfigWindow(
                    config_class=PipelineConfig,
                    initial_config=current_config,
                    scope_id="plate1"
                )

            window = WindowManager.show_or_focus("plate1", create_config_window)

            # Show and navigate to field
            WindowManager.show_or_focus(
                "plate1",
                create_config_window,
                field_path="well_filter_config.well_filter"
            )
        """
        # Check if window exists and is still valid
        lookup = cls._resolve_registered_window(scope_id)
        if lookup.is_present:
            window = lookup.window
            cls._focus_window(window, scope_id)
            logger.debug(
                "[WINDOW_MGR] Focused existing window for scope: %s",
                scope_id,
            )

            if item_id is not None or field_path is not None:
                cls._deferred_navigate(
                    window,
                    item_id,
                    field_path,
                    cls._navigation_driver(scope_id),
                )

            return window

        # Create new window
        logger.debug(f"[WINDOW_MGR] Creating new window for scope: {scope_id}")
        window = window_factory()
        cls._scoped_windows[scope_id] = window
        if navigation_driver is None:
            cls._navigation_drivers[scope_id] = NullWindowNavigationDriver()
        else:
            cls._navigation_drivers[scope_id] = navigation_driver
        if code_document_driver is not None:
            cls._code_document_drivers[scope_id] = code_document_driver

        # Auto-cleanup on close (hook into closeEvent)
        original_close = window.closeEvent

        def close_wrapper(event):
            cls.unregister(scope_id)
            original_close(event)

        window.closeEvent = close_wrapper

        # Show window
        window.show()
        QTimer.singleShot(0, lambda: cls.position_window_near_cursor(window))

        # Defer navigation if requested (waits for async widget creation)
        if item_id is not None or field_path is not None:
            cls._deferred_navigate(
                window,
                item_id,
                field_path,
                cls._navigation_driver(scope_id),
            )

        logger.debug(f"[WINDOW_MGR] Registered and showed new window for scope: {scope_id}")
        return window

    @classmethod
    def focus_and_navigate(
        cls,
        scope_id: str,
        item_id: Optional[str] = None,
        field_path: Optional[str] = None
    ) -> bool:
        """Focus window and navigate to specific item/field.

        Brings window to front and optionally navigates to item/field.
        Navigation only works if window implements the navigation protocol.

        IMPORTANT: Uses deferred navigation to handle async widget creation.
        The scroll/flash only triggers after:
        1. Window is shown and painted
        2. Target widgets are built (via _on_build_complete_callbacks)

        Args:
            scope_id: Window to focus
            item_id: Optional item to select (e.g., list index, tab name)
            field_path: Optional field to highlight (e.g., "well_filter_config.well_filter")

        Returns:
            True if window was found and focused, False otherwise

        Example:
            # Focus window and scroll to field (for inheritance tracking)
            WindowManager.focus_and_navigate(
                scope_id="plate1",
                field_path="well_filter_config.well_filter"
            )

            # Focus window and select item
            WindowManager.focus_and_navigate(
                scope_id="plate1::step_3",
                item_id="3"  # Select step 3 in list
            )
        """
        lookup = cls._resolve_registered_window(scope_id)
        if not lookup.is_present:
            logger.debug(f"[WINDOW_MGR] Cannot navigate - window not open for scope: {scope_id}")
            return False
        window = lookup.window

        cls._focus_window(window, scope_id)

        logger.debug(f"[WINDOW_MGR] Focused window for scope: {scope_id}")

        # Defer navigation to handle async widget creation
        # This ensures scroll/flash only happens after:
        # 1. Window is painted (QTimer.singleShot(0, ...))
        # 2. Target widgets exist (_on_build_complete_callbacks)
        cls._deferred_navigate(
            window,
            item_id,
            field_path,
            cls._navigation_driver(scope_id),
        )

        return True

    @classmethod
    def focus_widget_and_navigate(
        cls,
        window: QWidget,
        item_id: Optional[str] = None,
        field_path: Optional[str] = None,
    ) -> bool:
        """Focus/navigate the registered scope that owns a concrete Qt window."""
        target_window = window.window()
        for scope_id, registered_window in cls._scoped_windows.items():
            if registered_window is window or registered_window.window() is target_window:
                return cls.focus_and_navigate(
                    scope_id,
                    item_id=item_id,
                    field_path=field_path,
                )
        return False

    @classmethod
    def _deferred_navigate(
        cls,
        window: QWidget,
        item_id: Optional[str] = None,
        field_path: Optional[str] = None,
        navigation_driver: WindowNavigationDriver | None = None,
    ) -> None:
        """Internal: Deferred navigation that waits for async widget creation.

        Uses QTimer.singleShot(0, ...) to defer to after paint, then checks
        if widgets and nested managers are ready. If not, registers a callback
        on _on_build_complete_callbacks to retry.

        For nested field navigation (e.g., "well_filter_config.well_filter"),
        we check that nested managers exist at all path levels.
        """
        driver = navigation_driver
        if driver is None:
            driver = NullWindowNavigationDriver()
        request = RegisteredWindowNavigationRequest(
            window=window,
            item_id=item_id,
            field_path=field_path,
        )

        def _check_and_navigate():
            """Check if widgets are ready, navigate or schedule retry."""
            try:
                window.windowTitle()
            except RuntimeError:
                logger.debug(f"[WINDOW_MGR] Window deleted during deferred navigation")
                return

            readiness = driver.readiness(request)
            if not readiness.window_alive:
                return
            if readiness.needs_wait:
                if NavigationRetryScheduler.schedule(
                    request,
                    driver,
                    cls._navigation_retry_counts,
                    _check_and_navigate,
                ):
                    logger.debug(
                        "[WINDOW_MGR] Registered navigation retry "
                        "(wait_reason=%s)",
                        readiness.wait_reason,
                    )
                    return

            driver.execute(request)
            NavigationRetryScheduler.clear(request, cls._navigation_retry_counts)

        # Step 1: Defer to after current event loop (ensures window is at least shown)
        QTimer.singleShot(0, _check_and_navigate)

    @classmethod
    def register(
        cls,
        scope_id: str,
        window: QWidget,
        navigation_driver: WindowNavigationDriver | None = None,
        code_document_driver: "WindowCodeDocumentDriver | None" = None,
    ) -> None:
        """Register a window for singleton tracking.

        Used by windows that manage their own show() behavior (e.g., BaseFormDialog).
        The window is responsible for calling this from its show() method.

        IMPORTANT: The window must call unregister() in its closeEvent to allow reopening.
        BaseFormDialog does this automatically.

        Args:
            scope_id: Unique identifier for the window
            window: The window to register

        Example:
            class MyWindow(QDialog):
                def show(self):
                    scope_key = f"{self.scope_id}::{self.__class__.__name__}"
                    if WindowManager.is_open(scope_key):
                        WindowManager.focus_and_navigate(scope_key)
                        return  # Don't show duplicate
                    WindowManager.register(scope_key, self)
                    super().show()

                def closeEvent(self, event):
                    WindowManager.unregister(scope_key)
                    super().closeEvent(event)
        """
        if scope_id in cls._scoped_windows:
            logger.warning(f"[WINDOW_MGR] Overwriting existing window for scope: {scope_id}")

        cls._scoped_windows[scope_id] = window
        if navigation_driver is None:
            cls._navigation_drivers[scope_id] = NullWindowNavigationDriver()
        else:
            cls._navigation_drivers[scope_id] = navigation_driver
        if code_document_driver is not None:
            cls._code_document_drivers[scope_id] = code_document_driver

        # Eagerly create flash overlay so OpenGL context is ready before any flashes
        # This prevents first-paint glitches when GL initializes mid-render
        from pyqt_reactive.animation import WindowFlashOverlay
        WindowFlashOverlay.get_for_window(window)

        logger.debug(f"[WINDOW_MGR] Registered window for scope: {scope_id}")

    @classmethod
    def unregister(cls, scope_id: str) -> None:
        """Unregister a window from singleton tracking.

        Called by windows in their closeEvent to allow reopening.

        Args:
            scope_id: Scope to unregister
        """
        if scope_id in cls._scoped_windows:
            from pyqt_reactive.animation import WindowFlashOverlay

            WindowFlashOverlay.cleanup_window(cls._scoped_windows[scope_id])
            del cls._scoped_windows[scope_id]
            if scope_id in cls._navigation_drivers:
                del cls._navigation_drivers[scope_id]
            if scope_id in cls._code_document_drivers:
                del cls._code_document_drivers[scope_id]
            logger.debug(f"[WINDOW_MGR] Unregistered window: {scope_id}")

    @classmethod
    def require_code_document_driver(cls, scope_id: str) -> "WindowCodeDocumentDriver":
        """Return the code-document driver explicitly registered for a scope."""
        if scope_id not in cls._code_document_drivers:
            raise KeyError(
                f"Window scope has no code-document driver registered: {scope_id!r}"
            )
        return cls._code_document_drivers[scope_id]

    @classmethod
    def get_code_document_scopes(cls) -> list[str]:
        """Return open window scopes with registered code-document drivers."""
        open_scopes = set(cls.get_open_scopes())
        return [
            scope_id
            for scope_id in cls._code_document_drivers
            if scope_id in open_scopes
        ]

    @classmethod
    def is_open(cls, scope_id: str) -> bool:
        """Check if window is currently open and visible for scope_id.

        Args:
            scope_id: Scope to check

        Returns:
            True if window exists, is valid, AND is visible, False otherwise
        """
        lookup = cls._resolve_registered_window(scope_id, require_visible=True)
        return lookup.is_present

    @classmethod
    def get_window(cls, scope_id: str) -> Optional[QWidget]:
        """Return the window instance for a scope_id if present.

        Args:
            scope_id: Scope to lookup

        Returns:
            Window instance or None if not registered
        """
        lookup = cls._resolve_registered_window(scope_id)
        if lookup.is_present:
            return lookup.window
        return None

    @classmethod
    def close_window(cls, scope_id: str) -> bool:
        """Programmatically close window for scope_id.

        Args:
            scope_id: Scope to close

        Returns:
            True if window was found and closed, False otherwise
        """
        lookup = cls._resolve_registered_window(scope_id)
        if not lookup.is_present:
            return False

        lookup.window.close()  # Triggers closeEvent -> auto-cleanup
        return True

    @classmethod
    def get_open_scopes(cls) -> list[str]:
        """Get list of all currently open window scopes.

        Cleans up stale references as side effect.

        Returns:
            List of scope_ids for open windows
        """
        valid_scopes = []
        stale_scopes = []

        for scope_id, window in cls._scoped_windows.items():
            try:
                window.isVisible()
                valid_scopes.append(scope_id)
            except RuntimeError:
                stale_scopes.append(scope_id)

        # Cleanup stale references
        for scope_id in stale_scopes:
            del cls._scoped_windows[scope_id]
            if scope_id in cls._navigation_drivers:
                del cls._navigation_drivers[scope_id]
            if scope_id in cls._code_document_drivers:
                del cls._code_document_drivers[scope_id]
            logger.debug(f"[WINDOW_MGR] Cleaned up stale reference: {scope_id}")

        return valid_scopes
