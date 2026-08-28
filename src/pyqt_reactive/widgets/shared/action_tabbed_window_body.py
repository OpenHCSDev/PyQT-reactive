"""Tabbed window body with active-tab action widgets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from PyQt6.QtCore import QSignalBlocker, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QTabBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pyqt_reactive.forms.layout_constants import CURRENT_LAYOUT
from pyqt_reactive.services.tab_identity import (
    TabLabelDeclarationMixin as TabLabelDeclarationMixin,
)
from pyqt_reactive.widgets.shared.responsive_layout_widgets import ResponsiveTwoRowWidget


@dataclass(frozen=True, slots=True)
class ActionTabMaterialization:
    """Live content and actions constructed for one tab."""

    content: QWidget
    actions: QWidget | None = None


@dataclass(frozen=True, slots=True)
class ActionTabSpec:
    """One eager tab or one single-use tab materialization factory."""

    label: str
    content: QWidget | None = None
    actions: QWidget | None = None
    materialization_factory: Callable[[], ActionTabMaterialization] | None = None

    def __post_init__(self) -> None:
        if (self.content is None) == (self.materialization_factory is None):
            raise ValueError(
                "ActionTabSpec requires exactly one of content or "
                "materialization_factory."
            )
        if self.materialization_factory is not None and self.actions is not None:
            raise ValueError(
                "Lazy tab actions belong to ActionTabMaterialization, not ActionTabSpec."
            )


class ActionTabbedWindowBody(QWidget):
    """Render tabs on the left and the active tab's actions on the right."""

    current_changed = pyqtSignal(int)
    tab_materialized = pyqtSignal(int, object)
    tab_materialization_failed = pyqtSignal(int, object)

    def __init__(
        self,
        *,
        color_scheme: Any | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.color_scheme = color_scheme
        self._action_widgets: list[QWidget | None] = []
        self._active_actions_released = False
        self._materializations: list[ActionTabMaterialization | None] = []
        self._materialization_factories: list[
            Callable[[], ActionTabMaterialization] | None
        ] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tab_row = ResponsiveTwoRowWidget(
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
        stack_widget = spec.content if spec.content is not None else QWidget()
        index = self.content_stack.addWidget(stack_widget)
        materialization = (
            ActionTabMaterialization(spec.content, spec.actions)
            if spec.content is not None
            else None
        )
        self._materializations.append(materialization)
        self._materialization_factories.append(spec.materialization_factory)
        self._action_widgets.append(None)
        if materialization is not None:
            self._install_actions(index, materialization.actions)
        self.tab_bar.addTab(spec.label)
        if self.tab_bar.currentIndex() != self.content_stack.currentIndex():
            self.content_stack.setCurrentIndex(self.tab_bar.currentIndex())
        self._materialize(self.tab_bar.currentIndex())
        self.tab_bar.setVisible(self.content_stack.count() > 1)
        self._show_current_actions()
        self._sync_tab_row_visibility()
        return index

    def release_active_actions_widget(self) -> QWidget:
        """Transfer the stable active-action projection to an external layout."""

        if self._active_actions_released:
            raise RuntimeError("Active tab actions have already been released.")
        if not self.tab_row.release_widgets(self._active_actions_container):
            raise RuntimeError("Active tab actions are not owned by the tab row.")
        self._active_actions_released = True
        self._sync_tab_row_visibility()
        return self._active_actions_container

    def set_current_index(self, index: int) -> None:
        self.setCurrentIndex(index)

    def setCurrentIndex(self, index: int) -> None:
        if self.tab_bar.currentIndex() != index:
            # QTabBar emits currentChanged synchronously. That signal route is
            # the sole activation and failure-publication authority.
            self.tab_bar.setCurrentIndex(index)
            return

        # Re-selecting the current tab does not emit currentChanged.
        # Preserve the existing no-op synchronization behavior without
        # creating a second lazy-factory invocation path.
        self._materialize(index)
        self.content_stack.setCurrentIndex(index)
        self._show_current_actions()

    def current_index(self) -> int:
        return self.currentIndex()

    def currentIndex(self) -> int:
        return self.tab_bar.currentIndex()

    def current_widget(self) -> QWidget | None:
        return self.currentWidget()

    def currentWidget(self) -> QWidget | None:
        index = self.currentIndex()
        self._materialize(index)
        return self.widget(index)

    def widget(self, index: int) -> QWidget | None:
        if not 0 <= index < len(self._materializations):
            return None
        materialization = self._materializations[index]
        return materialization.content if materialization is not None else None

    def is_materialized(self, index: int) -> bool:
        """Return whether a tab's live content widget has been constructed."""
        return (
            0 <= index < len(self._materializations)
            and self._materializations[index] is not None
        )

    def materialize(self, index: int) -> ActionTabMaterialization:
        """Construct and return a lazy tab's live content and actions once."""
        self._materialize(index)
        if not 0 <= index < len(self._materializations):
            raise IndexError(f"Tab index is out of range: {index}")
        materialization = self._materializations[index]
        if materialization is None:
            raise RuntimeError(f"Tab {index} did not materialize.")
        return materialization

    def count(self) -> int:
        return self.content_stack.count()

    def _on_current_changed(self, index: int) -> None:
        if 0 <= index < self.content_stack.count():
            previous_index = self.content_stack.currentIndex()
            try:
                self._materialize(index)
            except Exception as error:
                with QSignalBlocker(self.tab_bar):
                    self.tab_bar.setCurrentIndex(previous_index)
                self._show_current_actions()
                self.tab_materialization_failed.emit(index, error)
                return
            self.content_stack.setCurrentIndex(index)
        self._show_current_actions()
        self.current_changed.emit(index)

    def _materialize(self, index: int) -> None:
        if not 0 <= index < len(self._materializations):
            return
        if self._materializations[index] is not None:
            return

        factory = self._materialization_factories[index]
        if factory is None:
            raise RuntimeError(
                f"Unmaterialized tab {index} has no materialization factory."
            )
        materialization = factory()
        if not isinstance(materialization, ActionTabMaterialization):
            raise TypeError(
                "ActionTabSpec.materialization_factory must return "
                "ActionTabMaterialization, "
                f"got {type(materialization).__name__}."
            )
        self._validate_materialization(materialization)

        placeholder = self.content_stack.widget(index)
        was_current = self.content_stack.currentIndex() == index
        self.content_stack.removeWidget(placeholder)
        self.content_stack.insertWidget(index, materialization.content)
        if was_current:
            self.content_stack.setCurrentIndex(index)
        placeholder.deleteLater()
        self._materializations[index] = materialization
        self._materialization_factories[index] = None
        self._install_actions(index, materialization.actions)
        self._show_current_actions()
        self.tab_materialized.emit(index, materialization)

    @staticmethod
    def _validate_materialization(
        materialization: ActionTabMaterialization,
    ) -> None:
        if not isinstance(materialization.content, QWidget):
            raise TypeError(
                "ActionTabMaterialization.content must be QWidget, "
                f"got {type(materialization.content).__name__}."
            )
        if materialization.actions is not None and not isinstance(
            materialization.actions,
            QWidget,
        ):
            raise TypeError(
                "ActionTabMaterialization.actions must be QWidget or None, "
                f"got {type(materialization.actions).__name__}."
            )

    def _install_actions(self, index: int, actions: QWidget | None) -> None:
        self._action_widgets[index] = actions
        if actions is None:
            return
        actions.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Fixed,
        )
        actions.setVisible(False)
        self._active_actions_layout.addWidget(actions)

    def _show_current_actions(self) -> None:
        current_index = self.tab_bar.currentIndex()
        for index, action_widget in enumerate(self._action_widgets):
            if action_widget is not None:
                action_widget.setVisible(index == current_index)

    def _sync_tab_row_visibility(self) -> None:
        """Show tab chrome only while it still presents tabs or actions."""

        self.tab_row.setVisible(
            self.content_stack.count() > 1 or not self._active_actions_released
        )

    def _apply_default_tab_style(self) -> None:
        if self.color_scheme is None:
            return
        self.tab_bar.setStyleSheet(f"""
            QTabBar::tab {{
                background-color: {self.color_scheme.to_hex(self.color_scheme.input_bg)};
                color: {self.color_scheme.to_hex(self.color_scheme.text_primary)};
                padding: 0px 16px;
                margin-right: 2px;
                border: 1px solid {self.color_scheme.to_hex(self.color_scheme.text_primary)};
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
