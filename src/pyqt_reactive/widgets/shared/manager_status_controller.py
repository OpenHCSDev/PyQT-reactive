"""Status-label presentation and scrolling for manager widgets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QLabel

from pyqt_reactive.strategies import (
    DefaultStatusPresentationStrategy,
    StatusPresentationInput,
)


@dataclass
class ManagerStatusController:
    """Owns manager status text rendering and optional marquee scrolling."""

    enable_scrolling: bool
    presentation_strategy: Any = None
    scroll_timer: QTimer | None = None
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
        status_label: QLabel | None,
        status_scroll: Any | None,
    ) -> None:
        """Render a status message, starting marquee scrolling when configured."""
        if not status_label:
            return

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
        status_label: QLabel | None,
        status_scroll: Any | None,
    ) -> None:
        """Re-apply the current message so scroll duplication matches new width."""
        if self.enable_scrolling and status_scroll:
            self.update(
                message=self.current_message,
                context=context,
                status_label=status_label,
                status_scroll=status_scroll,
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
        temp_label = QLabel(f"{rendered_message}{separator}")
        temp_label.setFont(status_label.font())
        temp_label.adjustSize()
        self.single_message_width = temp_label.width()

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
        if self.scroll_timer:
            self.scroll_timer.stop()
            self.scroll_timer = None

        status_scroll.horizontalScrollBar().setValue(0)
        self.scroll_position = 0

        label_width = status_label.width()
        scroll_width = status_scroll.viewport().width()

        if label_width > scroll_width:
            self.scroll_timer = QTimer(timer_parent)
            self.scroll_timer.setTimerType(Qt.TimerType.PreciseTimer)
            self.scroll_timer.timeout.connect(
                lambda: self._auto_scroll(status_label=status_label, status_scroll=status_scroll)
            )
            self.scroll_timer.start(50)

    def _auto_scroll(self, *, status_label: QLabel, status_scroll: Any) -> None:
        del status_label
        scrollbar = status_scroll.horizontalScrollBar()
        max_scroll = scrollbar.maximum()

        if max_scroll == 0:
            if self.scroll_timer:
                self.scroll_timer.stop()
            return

        self.scroll_position += 2
        reset_point = self.single_message_width or (max_scroll / 2)
        if self.scroll_position >= reset_point:
            self.scroll_position = 0

        scrollbar.setValue(int(self.scroll_position))
