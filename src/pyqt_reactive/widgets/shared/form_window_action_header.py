"""Reusable form-window header with staged action wrapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

from pyqt_reactive.widgets.shared.responsive_layout_widgets import StagedWrapLayout


@dataclass(frozen=True, slots=True)
class HeaderAction:
    """A stable widget reference inside a form-window action group."""

    id: str
    widget: QWidget


@dataclass(frozen=True, slots=True)
class HeaderActionGroup:
    """A named action group for staged header wrapping."""

    id: str
    actions: Sequence[HeaderAction]


class FormWindowActionHeader(QWidget):
    """Render a form title plus grouped actions with staged wrapping."""

    def __init__(
        self,
        *,
        title_text: str,
        action_groups: Sequence[HeaderActionGroup],
        stay_priority: Sequence[str],
        right_aligned_group_ids: Sequence[str] = (),
        title_color: str | None = None,
        title_background: str = "transparent",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.header_label = self._build_title_label(
            title_text=title_text,
            title_color=title_color,
            title_background=title_background,
        )
        self.actions = {
            action.id: action.widget
            for group in action_groups
            for action in group.actions
        }

        title_group = self._group_widgets([self.header_label])
        groups = [("title", title_group)]
        groups.extend(
            (group.id, self._group_widgets([action.widget for action in group.actions]))
            for group in action_groups
        )

        self._layout_widget = StagedWrapLayout(parent=self)
        self._layout_widget.set_groups(
            groups,
            ["title", *stay_priority],
            right_align_names=right_aligned_group_ids,
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._layout_widget)

    def action(self, action_id: str) -> QWidget:
        """Return a stable action widget by ID."""
        return self.actions[action_id]

    @staticmethod
    def _build_title_label(
        *,
        title_text: str,
        title_color: str | None,
        title_background: str,
    ) -> QLabel:
        label = QLabel(title_text)
        label.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if title_color is not None:
            label.setStyleSheet(
                f"color: {title_color}; background-color: {title_background};"
            )
        return label

    @staticmethod
    def _group_widgets(widgets: Sequence[QWidget]) -> QWidget:
        group = QWidget()
        layout = QHBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for widget in widgets:
            layout.addWidget(widget)
        return group
