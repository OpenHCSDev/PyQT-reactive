"""Status-label presentation and scrolling for manager widgets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QLabel

from formbridge.strategies.status_presentation import (
    DefaultStatusPresentationStrategy,
    StatusPresentationInput,
)
from pyqt_reactive.widgets.shared.manager_ui_scaffold import ManagerHeaderParts


@dataclass
class ManagerStatusController:
    """Owns manager status text rendering and optional marquee scrolling.

    One marquee timer, parented to the manager widget, lives as long as the
    widget; each status message restarts it.
    """

    enable_scrolling: bool
    presentation_strategy: Any = None
    scroll_timer: QTimer | None = None
    scroll_area: Any = None
    scroll_position: int = 0
    single_message_width: int = 0
    current_message: str = "Ready"

    def __post_init__(self) -> None:
        if self.presentation_strategy is None:
            self.presentation_strategy = DefaultStatusPresentationStrategy()

    def update(
        self,
        *,
        message: str,
        context: Any,
        manager_header: ManagerHeaderParts | None,
    ) -> None:
        """Render a status message, starting marquee scrolling when configured."""
        if manager_header is None:
            return
        status_label = manager_header.status_label
        status_scroll = manager_header.status_scroll

        presentation = self.presentation_strategy.present(
            StatusPresentationInput(message=message, context=context)
        )
        rendered_message = presentation.text
        self.current_message = rendered_message

        if not self.enable_scrolling or not status_scroll:
            status_label.setText(rendered_message)
            return

        self._render_scrolling_message(
            rendered_message=rendered_message,
            status_label=status_label,
            status_scroll=status_scroll,
            timer_parent=context,
        )

    def recalculate_after_resize(
        self,
        *,
        context: Any,
        manager_header: ManagerHeaderParts | None,
    ) -> None:
        """Re-apply the current message so scroll duplication matches new width."""
        status_scroll = (
            None if manager_header is None else manager_header.status_scroll
        )
        if self.enable_scrolling and status_scroll:
            self.update(
                message=self.current_message,
                context=context,
                manager_header=manager_header,
            )

    def _render_scrolling_message(
        self,
        *,
        rendered_message: str,
        status_label: QLabel,
        status_scroll: Any,
        timer_parent: Any,
    ) -> None:
        status_label.setText(rendered_message)
        status_label.adjustSize()

        separator = "     "
        self.single_message_width = status_label.fontMetrics().horizontalAdvance(
            f"{rendered_message}{separator}"
        )

        label_width = status_label.width()
        scroll_width = status_scroll.viewport().width()

        if label_width > scroll_width:
            status_label.setText(
                f"{rendered_message}{separator}{rendered_message}{separator}"
            )
            status_label.adjustSize()

        self._restart_scrolling(
            status_label=status_label,
            status_scroll=status_scroll,
            timer_parent=timer_parent,
        )

    def _restart_scrolling(
        self,
        *,
        status_label: QLabel,
        status_scroll: Any,
        timer_parent: Any,
    ) -> None:
        status_scroll.horizontalScrollBar().setValue(0)
        self.scroll_position = 0
        self.scroll_area = status_scroll

        if status_label.width() <= status_scroll.viewport().width():
            if self.scroll_timer is not None:
                self.scroll_timer.stop()
            return

        if self.scroll_timer is None:
            self.scroll_timer = QTimer(timer_parent)
            self.scroll_timer.setTimerType(Qt.TimerType.PreciseTimer)
            self.scroll_timer.timeout.connect(self._auto_scroll)
        self.scroll_timer.start(50)

    def _auto_scroll(self) -> None:
        scrollbar = self.scroll_area.horizontalScrollBar()
        max_scroll = scrollbar.maximum()

        if max_scroll == 0:
            self.scroll_timer.stop()
            return

        self.scroll_position += 2
        reset_point = self.single_message_width or (max_scroll / 2)
        if self.scroll_position >= reset_point:
            self.scroll_position = 0

        scrollbar.setValue(int(self.scroll_position))
