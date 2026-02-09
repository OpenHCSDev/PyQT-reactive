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
from typing import Dict, Callable, Optional, Protocol
from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QCursor, QGuiApplication
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtCore import QTimer

from objectstate import ObjectStateRegistry

logger = logging.getLogger(__name__)


class NavigableWindow(Protocol):
    """Protocol for windows that support navigation to items/fields.

    Windows can optionally implement these methods to support navigation.
    """

    def select_and_scroll_to_item(self, item_id: str) -> None:
        """Select and scroll to item (e.g., list item, tab).

        Args:
            item_id: Identifier for the item to navigate to
        """
        ...

    def select_and_scroll_to_field(self, field_path: str) -> None:
        """Select and scroll to field (e.g., tree node, form widget).

        Args:
            field_path: Dotted path to field (e.g., "well_filter_config.well_filter")
        """
        ...


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

    @classmethod
    def position_window_near_cursor(
        cls,
        window: QWidget,
        offset: int = 0,
        avoid_widgets: list[QWidget] | None = None,
    ) -> None:
        """Place window centered on mouse cursor without overlapping floating windows."""
        if avoid_widgets is None:
            avoid_widgets = getattr(window, "_avoid_widgets", None) or []
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
        for widget in avoid_widgets or []:
            try:
                avoid_rects.append(widget.frameGeometry())
            except Exception:
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
                except Exception:
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

        if not candidates:
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
    def show_or_focus(
        cls,
        scope_id: str,
        window_factory: Callable[[], QWidget],
        item_id: Optional[str] = None,
        field_path: Optional[str] = None
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
        if scope_id in cls._scoped_windows:
            window = cls._scoped_windows[scope_id]
            try:
                # Test if window still exists (Qt doesn't auto-cleanup deleted widgets)
                # Note: Just accessing any property will raise RuntimeError if deleted
                _ = window.windowTitle()

                # Window exists - bring to front regardless of visibility
                # (window may be hidden, minimized, or still initializing - all valid states)
                if not window.isVisible():
                    window.show()

                window.raise_()
                window.activateWindow()

                # Restore if minimized
                if window.isMinimized():
                    window.showNormal()

                logger.debug(f"[WINDOW_MGR] Focused existing window for scope: {scope_id}")

                # Defer navigation if requested
                if item_id or field_path:
                    cls._deferred_navigate(window, item_id, field_path)

                return window

            except RuntimeError:
                # Window was deleted but not cleaned from registry - fail loud
                logger.warning(f"[WINDOW_MGR] Stale window reference detected for scope: {scope_id}")
                del cls._scoped_windows[scope_id]

        # Create new window
        logger.debug(f"[WINDOW_MGR] Creating new window for scope: {scope_id}")
        window = window_factory()
        cls._scoped_windows[scope_id] = window

        # Auto-cleanup on close (hook into closeEvent)
        original_close = window.closeEvent if hasattr(window, 'closeEvent') else None

        def close_wrapper(event):
            # Unregister window before closing
            if scope_id in cls._scoped_windows:
                del cls._scoped_windows[scope_id]
                logger.debug(f"[WINDOW_MGR] Unregistered window on close: {scope_id}")

            # Call original closeEvent
            if original_close:
                original_close(event)

        window.closeEvent = close_wrapper

        # Show window
        window.show()
        QTimer.singleShot(0, lambda: cls.position_window_near_cursor(window))

        # Defer navigation if requested (waits for async widget creation)
        if item_id or field_path:
            cls._deferred_navigate(window, item_id, field_path)

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
        window = cls._scoped_windows.get(scope_id)
        if not window:
            logger.debug(f"[WINDOW_MGR] Cannot navigate - window not open for scope: {scope_id}")
            return False

        try:
            # Test if window still exists by accessing any property
            _ = window.windowTitle()

            # Ensure window is visible (may be hidden or still initializing)
            if not window.isVisible():
                window.show()

            # Bring window to front only if not already the active window
            # This prevents window jumping when navigating within the same window (e.g., different tabs)
            app = QApplication.instance()
            is_already_active = app and app.activeWindow() == window
            if not is_already_active:
                window.raise_()
                window.activateWindow()
            else:
                logger.debug(f"[WINDOW_MGR] Window already active, skipping raise/activate: {scope_id}")

            # Restore if minimized
            if window.isMinimized():
                window.showNormal()

            logger.debug(f"[WINDOW_MGR] Focused window for scope: {scope_id}")

            # Defer navigation to handle async widget creation
            # This ensures scroll/flash only happens after:
            # 1. Window is painted (QTimer.singleShot(0, ...))
            # 2. Target widgets exist (_on_build_complete_callbacks)
            cls._deferred_navigate(window, item_id, field_path)

            return True

        except RuntimeError:
            # Window was deleted - cleanup stale reference
            logger.warning(f"[WINDOW_MGR] Window deleted during navigation for scope: {scope_id}")
            del cls._scoped_windows[scope_id]
            return False

    @classmethod
    def _deferred_navigate(
        cls,
        window: QWidget,
        item_id: Optional[str] = None,
        field_path: Optional[str] = None
    ) -> None:
        """Internal: Deferred navigation that waits for async widget creation.

        Uses QTimer.singleShot(0, ...) to defer to after paint, then checks
        if widgets and nested managers are ready. If not, registers a callback
        on _on_build_complete_callbacks to retry.

        For nested field navigation (e.g., "well_filter_config.well_filter"),
        we check that nested managers exist at all path levels.
        """
        def _do_navigation():
            """Actually perform the navigation (scroll + flash)."""
            try:
                # Validate window still exists
                _ = window.windowTitle()
            except RuntimeError:
                logger.debug(f"[WINDOW_MGR] Window deleted during deferred navigation")
                return

            # Navigate to item if window supports it (duck typing)
            if item_id and hasattr(window, 'select_and_scroll_to_item'):
                logger.debug(f"[WINDOW_MGR] Deferred navigating to item: {item_id}")
                window.select_and_scroll_to_item(item_id)

            # Navigate to field if window supports it (duck typing)
            if field_path and hasattr(window, 'select_and_scroll_to_field'):
                # Eagerly create flash overlay BEFORE navigation to ensure it's ready for flash
                from pyqt_reactive.animation import WindowFlashOverlay
                WindowFlashOverlay.get_for_window(window)
                logger.debug(f"[WINDOW_MGR] Deferred navigating to field: {field_path}")
                window.select_and_scroll_to_field(field_path)
            elif field_path:
                logger.debug(f"[WINDOW_MGR] Field path provided but window has no select_and_scroll_to_field: {field_path}")

        def _check_nested_manager_exists(form_manager, field_path: str) -> bool:
            """Check if all nested managers in the field path exist.

            For "well_filter_config.well_filter", checks:
            1. nested_managers['well_filter_config'] exists
            2. (No further check needed since 'well_filter' is a widget, not nested)

            Returns True if path is valid, False if nested manager is missing.
            """
            if '.' not in field_path:
                # Single-level path, no nested manager needed
                return True

            parts = field_path.split('.')
            current_manager = form_manager

            # Check all but the last part (which is the field/leaf)
            for i, part in enumerate(parts[:-1]):
                if not hasattr(current_manager, 'nested_managers'):
                    logger.debug(f"[WINDOW_MGR] No nested_managers attribute at depth {i}")
                    return False
                if part not in current_manager.nested_managers:
                    logger.debug(f"[WINDOW_MGR] Nested manager '{part}' not found at depth {i}")
                    return False
                current_manager = current_manager.nested_managers[part]

            return True

        def _check_and_navigate():
            """Check if widgets are ready, navigate or register callback."""
            try:
                # Validate window still exists
                _ = window.windowTitle()
            except RuntimeError:
                return

            # Check if we need to wait for async widget creation
            needs_wait = False
            wait_reason = None

            if field_path and hasattr(window, 'form_manager'):
                form_manager = window.form_manager

                # Check 1: Root widgets must exist
                if hasattr(form_manager, 'widgets') and not form_manager.widgets:
                    logger.debug(f"[WINDOW_MGR] Root widgets not ready, waiting...")
                    needs_wait = True
                    wait_reason = "root widgets"
                # Check 2: For nested field paths, check nested managers exist
                elif '.' in field_path:
                    if not _check_nested_manager_exists(form_manager, field_path):
                        logger.debug(f"[WINDOW_MGR] Nested manager not ready for '{field_path}', waiting...")
                        needs_wait = True
                        wait_reason = "nested manager"

            if item_id and hasattr(window, 'item_list'):
                # For list-based navigation, check if items exist
                if hasattr(window, '_scope_to_list_item'):
                    if not window._scope_to_list_item:
                        logger.debug(f"[WINDOW_MGR] List items not ready, waiting...")
                        needs_wait = True
                        wait_reason = "list items"

            if needs_wait:
                # Register callback to retry after build completes
                if hasattr(window, 'form_manager'):
                    callbacks = getattr(window.form_manager, '_on_build_complete_callbacks', None)
                    if callbacks is not None:
                        # Track retry count to prevent infinite loops
                        retry_count = getattr(window, '_nav_retry_count', 0)
                        if retry_count < 10:  # Max 10 retries
                            def retry_with_callback():
                                # Increment retry count
                                window._nav_retry_count = getattr(window, '_nav_retry_count', 0) + 1
                                logger.debug(f"[WINDOW_MGR] Build complete, retrying navigation (attempt {window._nav_retry_count})")
                                # Schedule re-check instead of direct navigation
                                # This allows nested managers to be fully populated
                                QTimer.singleShot(50, _check_and_navigate)

                            callbacks.append(retry_with_callback)
                            logger.debug(f"[WINDOW_MGR] Registered build-complete callback for navigation (wait_reason={wait_reason})")
                            return
                        else:
                            logger.warning(f"[WINDOW_MGR] Max retries reached for navigation, giving up")

            # Widgets are ready or no wait needed - navigate now
            _do_navigation()

        # Step 1: Defer to after current event loop (ensures window is at least shown)
        QTimer.singleShot(0, _check_and_navigate)

    @classmethod
    def register(cls, scope_id: str, window: QWidget) -> None:
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
            del cls._scoped_windows[scope_id]
            logger.debug(f"[WINDOW_MGR] Unregistered window: {scope_id}")

    @classmethod
    def is_open(cls, scope_id: str) -> bool:
        """Check if window is currently open and visible for scope_id.

        Args:
            scope_id: Scope to check

        Returns:
            True if window exists, is valid, AND is visible, False otherwise
        """
        if scope_id not in cls._scoped_windows:
            return False

        try:
            window = cls._scoped_windows[scope_id]
            is_visible = window.isVisible()
            if not is_visible:
                # Window was closed/hidden but not unregistered - clean up
                del cls._scoped_windows[scope_id]
                logger.debug(f"[WINDOW_MGR] Cleaned up closed window: {scope_id}")
                return False
            return True
        except RuntimeError:
            # Stale reference (C++ object deleted)
            del cls._scoped_windows[scope_id]
            return False

    @classmethod
    def get_window(cls, scope_id: str) -> Optional[QWidget]:
        """Return the window instance for a scope_id if present.

        Args:
            scope_id: Scope to lookup

        Returns:
            Window instance or None if not registered
        """
        return cls._scoped_windows.get(scope_id)

    @classmethod
    def close_window(cls, scope_id: str) -> bool:
        """Programmatically close window for scope_id.

        Args:
            scope_id: Scope to close

        Returns:
            True if window was found and closed, False otherwise
        """
        if scope_id not in cls._scoped_windows:
            return False

        try:
            window = cls._scoped_windows[scope_id]
            window.close()  # Triggers closeEvent → auto-cleanup
            return True
        except RuntimeError:
            # Already deleted
            del cls._scoped_windows[scope_id]
            return False

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
            logger.debug(f"[WINDOW_MGR] Cleaned up stale reference: {scope_id}")

        return valid_scopes
