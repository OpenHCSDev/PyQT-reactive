"""Shared scope-window navigation service."""

from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget

from pyqt_reactive.services.scope_window_factory import WindowFactory
from pyqt_reactive.services.window_navigation import (
    WindowNavigationRequest,
    WindowNavigationResult,
)


class ScopeWindowNavigationService:
    """Open/focus WindowManager scopes and navigate to requested UI targets."""

    @classmethod
    def navigate(
        cls,
        request: WindowNavigationRequest,
    ) -> WindowNavigationResult:
        from pyqt_reactive.services.window_manager import WindowManager

        open_window = WindowManager.get_window(request.scope_id)
        if open_window is not None:
            focused = WindowManager.focus_and_navigate(
                request.scope_id,
                item_id=request.item_id,
                field_path=request.field_path,
            )
            return WindowNavigationResult(
                request=request,
                window=open_window,
                focused=focused,
                created=False,
            )

        if not request.create_if_missing:
            return WindowNavigationResult(
                request=request,
                window=None,
                focused=False,
                created=False,
            )

        created_window = WindowFactory.create_window_for_scope(
            request.scope_id,
            request.object_state,
        )
        if created_window is None:
            return WindowNavigationResult(
                request=request,
                window=None,
                focused=False,
                created=False,
            )

        cls._position_created_window(created_window, request)

        focused = WindowManager.focus_and_navigate(
            request.scope_id,
            item_id=request.item_id,
            field_path=request.field_path,
        )
        return WindowNavigationResult(
            request=request,
            window=created_window,
            focused=focused,
            created=True,
        )

    @staticmethod
    def _position_created_window(
        window: QWidget,
        request: WindowNavigationRequest,
    ) -> None:
        if len(request.avoid_widgets) == 0:
            return
        avoid_widgets = request.avoid_widgets
        from pyqt_reactive.services.window_manager import WindowManager

        def position_near_request_source() -> None:
            WindowManager.position_window_near_cursor(
                window,
                avoid_widgets=avoid_widgets,
            )

        QTimer.singleShot(0, position_near_request_source)
