"""One tab and one action button per nested config of a live ObjectState."""

from __future__ import annotations

from objectstate import DottedFieldPath

from collections.abc import Sequence
from dataclasses import dataclass

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QPushButton, QWidget
from python_introspect import Enableable

from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.shared.tabbed_form_widget import (
    TabbedFormConfig,
    TabbedFormWidget,
    TabConfig,
)


@dataclass(frozen=True, slots=True)
class ConfigAction:
    """An action that one nested config of the state configures and enables."""

    field_name: str
    """The nested config's field in the state."""
    title: str
    """The config's tab title."""
    button_text: str

    @property
    def enabled_path(self) -> str:
        """The nested config's ``Enableable`` field, which switches the action on."""
        return f"{self.field_name}.{Enableable.require_parameter_name()}"


class ConfigActionTabs(TabbedFormWidget):
    """Edits each action's config in a tab and offers its button beside the tabs.

    The form is live: there is no save or cancel, so every edit becomes the
    state's saved baseline. A button is clickable when its config is enabled
    and the owner reports a target (:meth:`set_target_available`).
    """

    action_requested = pyqtSignal(object)
    """Emitted with the :class:`ConfigAction` whose button was clicked."""

    def __init__(
        self,
        state,
        actions: Sequence[ConfigAction],
        color_scheme: ColorScheme | None = None,
        parent: QWidget | None = None,
    ) -> None:
        color_scheme = color_scheme or ColorScheme()
        self.actions = tuple(actions)
        self._target_available = False
        self.buttons: dict[ConfigAction, QPushButton] = {}
        for action in self.actions:
            button = QPushButton(action.button_text)
            button.setStyleSheet(color_scheme.styles.generate_button_style())
            self.buttons[action] = button
        super().__init__(
            state=state,
            config=TabbedFormConfig(
                tabs=[
                    TabConfig(name=action.title, field_ids=[action.field_name])
                    for action in self.actions
                ],
                color_scheme=color_scheme,
                use_scroll_area=True,
                header_widgets=list(self.buttons.values()),
            ),
            parent=parent,
        )
        for action, button in self.buttons.items():
            button.clicked.connect(
                lambda _checked, action=action: self.action_requested.emit(action)
            )
        self.parameter_changed.connect(self._on_live_edit)
        self._refresh_buttons()

    def enabled_actions(self) -> tuple[ConfigAction, ...]:
        """The actions whose config is switched on."""
        return tuple(
            action
            for action in self.actions
            if DottedFieldPath(action.enabled_path).bind(self.state).value is True
        )

    def set_target_available(self, available: bool) -> None:
        """Tell the buttons whether there is something to act on."""
        self._target_available = available
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        enabled = self.enabled_actions()
        for action, button in self.buttons.items():
            button.setEnabled(self._target_available and action in enabled)

    def _on_live_edit(self, _param_name: str, _value: object) -> None:
        self.state.mark_saved()
        self._refresh_buttons()
