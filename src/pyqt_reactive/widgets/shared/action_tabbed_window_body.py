"""Tabbed window body with active-tab action widgets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QTabBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pyqt_reactive.forms.layout_constants import CURRENT_LAYOUT
from pyqt_reactive.widgets.shared.responsive_layout_widgets import ResponsiveTwoRowWidget


@dataclass(frozen=True, slots=True)
class ActionTabSpec:
    """One tab plus its optional active-tab action widget."""

    label: str
    content: QWidget
    actions: QWidget | None = None


class ActionTabbedWindowBody(QWidget):
    """Render tabs on the left and the active tab's actions on the right."""

    current_changed = pyqtSignal(int)

    def __init__(
        self,
        *,
        color_scheme: Any | None = None,
        width_threshold: int = 600,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.color_scheme = color_scheme
        self._action_widgets: list[QWidget | None] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tab_row = ResponsiveTwoRowWidget(
            width_threshold=width_threshold,
            parent=self,
        )
        self.tab_bar = QTabBar()
        self.tab_bar.setExpanding(False)
        self.tab_bar.setUsesScrollButtons(False)
        self.tab_bar.setFixedHeight(CURRENT_LAYOUT.button_height)
        self.tab_bar.currentChanged.connect(self._on_current_changed)
        self.tab_row.add_left_widget(self.tab_bar)

        self._active_actions_container = QWidget()
        self._active_actions_layout = QHBoxLayout(self._active_actions_container)
        self._active_actions_layout.setContentsMargins(0, 0, 0, 0)
        self._active_actions_layout.setSpacing(0)
        self.tab_row.add_right_widget(self._active_actions_container)

        layout.addWidget(self.tab_row)

        self.content_container = QWidget()
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        layout.addWidget(self.content_container, 1)

        self.content_stack = QStackedWidget()
        self.content_layout.addWidget(self.content_stack)

        self._apply_default_tab_style()

    def add_tab(self, spec: ActionTabSpec) -> int:
        """Add a tab and its optional action widget."""
        index = self.content_stack.addWidget(spec.content)
        self.tab_bar.addTab(spec.label)
        self._action_widgets.append(spec.actions)
        if spec.actions is not None:
            spec.actions.setSizePolicy(
                QSizePolicy.Policy.Maximum,
                QSizePolicy.Policy.Fixed,
            )
            spec.actions.setVisible(False)
            self._active_actions_layout.addWidget(spec.actions)
        if self.tab_bar.currentIndex() != self.content_stack.currentIndex():
            self.content_stack.setCurrentIndex(self.tab_bar.currentIndex())
        self.tab_bar.setVisible(self.content_stack.count() > 1)
        self._show_current_actions()
        return index

    def set_current_index(self, index: int) -> None:
        self.setCurrentIndex(index)

    def setCurrentIndex(self, index: int) -> None:
        self.tab_bar.setCurrentIndex(index)
        self.content_stack.setCurrentIndex(index)
        self._show_current_actions()

    def current_index(self) -> int:
        return self.currentIndex()

    def currentIndex(self) -> int:
        return self.tab_bar.currentIndex()

    def current_widget(self) -> QWidget | None:
        return self.currentWidget()

    def currentWidget(self) -> QWidget | None:
        return self.content_stack.currentWidget()

    def widget(self, index: int) -> QWidget | None:
        return self.content_stack.widget(index)

    def count(self) -> int:
        return self.content_stack.count()

    def _on_current_changed(self, index: int) -> None:
        if 0 <= index < self.content_stack.count():
            self.content_stack.setCurrentIndex(index)
        self._show_current_actions()
        self.current_changed.emit(index)

    def _show_current_actions(self) -> None:
        current_index = self.tab_bar.currentIndex()
        for index, action_widget in enumerate(self._action_widgets):
            if action_widget is not None:
                action_widget.setVisible(index == current_index)

    def _apply_default_tab_style(self) -> None:
        if self.color_scheme is None:
            return
        self.tab_bar.setStyleSheet(f"""
            QTabBar::tab {{
                background-color: {self.color_scheme.to_hex(self.color_scheme.input_bg)};
                color: {self.color_scheme.to_hex(self.color_scheme.text_primary)};
                padding: 0px 16px;
                margin-right: 2px;
                border: none;
                border-radius: 4px 4px 0 0;
                height: {CURRENT_LAYOUT.button_height}px;
            }}
            QTabBar::tab:selected {{
                background-color: {self.color_scheme.to_hex(self.color_scheme.selection_bg)};
            }}
            QTabBar::tab:hover {{
                background-color: {self.color_scheme.to_hex(self.color_scheme.button_hover_bg)};
            }}
        """)
