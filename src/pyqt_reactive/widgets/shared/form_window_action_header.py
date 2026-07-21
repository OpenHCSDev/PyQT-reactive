"""Reusable form-window header with staged action wrapping."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

from pyqt_reactive.widgets.shared.responsive_layout_widgets import StagedWrapLayout


class _WrappingHeaderLabel(QLabel):
    """Expose one-line preferred width while retaining compact word wrapping."""

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method name
        metrics = self.fontMetrics()
        margin = self.margin()
        one_line_size = metrics.size(
            int(Qt.TextFlag.TextSingleLine.value),
            self.text(),
        )
        return QSize(
            one_line_size.width() + (2 * margin),
            one_line_size.height() + (2 * margin),
        )


class _HeaderActionGroupWidget(QWidget):
    """Expose current-width height for groups containing wrapped labels."""

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method name
        hint = super().sizeHint()
        if self.width() <= 0 or not self.hasHeightForWidth():
            return hint
        required_height = self.heightForWidth(self.width())
        if required_height < 0:
            return hint
        return QSize(
            hint.width(),
            required_height,
        )


@dataclass(frozen=True, slots=True)
class HeaderAction:
    """A stable widget reference inside a form-window action group."""

    id: str
    widget: QWidget


class HeaderActionGroupRole(Enum):
    """Semantic placement owned by a form-window action group."""

    TITLE_COMPANION = "title_companion"
    AUXILIARY = "auxiliary"
    COMMIT = "commit"


@dataclass(frozen=True, slots=True)
class HeaderActionGroup:
    """A named action group for staged header wrapping."""

    id: str
    actions: Sequence[HeaderAction]
    role: HeaderActionGroupRole | None = None


class FormWindowActionHeader(QWidget):
    """Render a form title plus grouped actions with staged wrapping."""

    def __init__(
        self,
        *,
        title_text: str,
        action_groups: Sequence[HeaderActionGroup],
        stay_priority: Sequence[str] | None = None,
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

        groups, resolved_stay_priority, resolved_right_aligned_ids = (
            self._resolve_layout_groups(
                action_groups=action_groups,
                stay_priority=stay_priority,
                right_aligned_group_ids=right_aligned_group_ids,
            )
        )

        self._layout_widget = StagedWrapLayout(parent=self)
        for row_widget in (
            self._layout_widget._row1_widget,
            self._layout_widget._row2_widget,
        ):
            row_policy = row_widget.sizePolicy()
            row_policy.setVerticalPolicy(QSizePolicy.Policy.Preferred)
            row_widget.setSizePolicy(row_policy)
        self._layout_widget.set_groups(
            groups,
            resolved_stay_priority,
            right_align_names=resolved_right_aligned_ids,
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._layout_widget)

    def action(self, action_id: str) -> QWidget:
        """Return a stable action widget by ID."""
        return self.actions[action_id]

    def refresh_layout(self) -> None:
        """Recompute wrapping after caller-owned action visibility changes."""

        self._layout_widget.refresh_layout()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method name
        """Return the current-width height required by a wrapped title."""

        hint = super().sizeHint()
        if self.width() <= 0:
            return hint
        required_height = self._layout_widget.heightForWidth(
            self.contentsRect().width()
        )
        if required_height < 0:
            return hint
        return QSize(
            hint.width(),
            required_height,
        )

    def _resolve_layout_groups(
        self,
        *,
        action_groups: Sequence[HeaderActionGroup],
        stay_priority: Sequence[str] | None,
        right_aligned_group_ids: Sequence[str],
    ) -> tuple[list[tuple[str, QWidget]], list[str], list[str]]:
        declared_roles = tuple(group.role for group in action_groups)
        uses_semantic_roles = any(role is not None for role in declared_roles)
        if not uses_semantic_roles:
            if stay_priority is None:
                raise ValueError(
                    "FormWindowActionHeader requires semantic group roles or "
                    "an explicit stay_priority."
                )
            title_group = self._group_widgets([self.header_label])
            groups = [("title", title_group)]
            groups.extend(
                (
                    group.id,
                    self._group_widgets([action.widget for action in group.actions]),
                )
                for group in action_groups
            )
            return (
                groups,
                ["title", *stay_priority],
                list(right_aligned_group_ids),
            )

        if any(role is None for role in declared_roles):
            raise ValueError(
                "Semantic form headers require a role on every action group."
            )
        if stay_priority is not None or right_aligned_group_ids:
            raise ValueError(
                "Semantic form headers derive priority and alignment from group roles."
            )

        title_actions = [
            action.widget
            for group in action_groups
            if group.role is HeaderActionGroupRole.TITLE_COMPANION
            for action in group.actions
        ]
        title_group = self._group_widgets([self.header_label, *title_actions])
        auxiliary_groups = [
            group
            for group in action_groups
            if group.role is HeaderActionGroupRole.AUXILIARY
        ]
        commit_groups = [
            group
            for group in action_groups
            if group.role is HeaderActionGroupRole.COMMIT
        ]
        visible_groups = [*auxiliary_groups, *commit_groups]
        groups = [("title", title_group)]
        groups.extend(
            (
                group.id,
                self._group_widgets([action.widget for action in group.actions]),
            )
            for group in visible_groups
        )
        auxiliary_ids = [group.id for group in auxiliary_groups]
        commit_ids = [group.id for group in commit_groups]
        return (
            groups,
            [*commit_ids, "title", *auxiliary_ids],
            [*auxiliary_ids, *commit_ids],
        )

    @staticmethod
    def _build_title_label(
        *,
        title_text: str,
        title_color: str | None,
        title_background: str,
    ) -> QLabel:
        label = _WrappingHeaderLabel(title_text)
        label.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        size_policy = QSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        size_policy.setHeightForWidth(True)
        label.setSizePolicy(size_policy)
        if title_color is not None:
            label.setStyleSheet(
                f"color: {title_color}; background-color: {title_background};"
            )
        return label

    @staticmethod
    def _group_widgets(widgets: Sequence[QWidget]) -> QWidget:
        group = _HeaderActionGroupWidget()
        layout = QHBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for widget in widgets:
            layout.addWidget(widget)
        return group
