"""Configurable application keyboard shortcuts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Generic, TypeVar

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QApplication

ConfigT = TypeVar("ConfigT")


class KeyEventSequence:
    """Convert Qt key events into portable key-sequence text."""

    @classmethod
    def from_event(cls, event) -> str | None:
        if event.type() != QEvent.Type.KeyPress:
            return None
        sequence = QKeySequence(event.keyCombination())
        if sequence.isEmpty():
            return None
        return sequence.toString(QKeySequence.SequenceFormat.PortableText)


class CodeEditorFocus:
    """Application shortcuts yield while a code editor dialog has keyboard focus."""

    @staticmethod
    def allows_application_shortcuts() -> bool:
        from pyqt_reactive.widgets.editors.simple_code_editor import (
            CodeEditorDialog,
            QScintillaCodeEditorDialog,
        )

        widget = QApplication.focusWidget()
        while widget is not None:
            if isinstance(widget, (QScintillaCodeEditorDialog, CodeEditorDialog)):
                return False
            widget = widget.parentWidget()
        return True


class ApplicationShortcutFilter(QObject):
    """Application-wide event filter routing configured key sequences to commands."""

    def __init__(self, actions: Mapping[str, Callable[[], None]]) -> None:
        super().__init__()
        self._actions = dict(actions)

    def replace_actions(self, actions: Mapping[str, Callable[[], None]]) -> None:
        """Replace the complete configured key-to-command projection."""

        self._actions = dict(actions)

    def eventFilter(self, obj, event):  # noqa: N802 - Qt virtual method name
        del obj
        sequence = KeyEventSequence.from_event(event)
        if sequence is None:
            return False
        if sequence not in self._actions:
            return False
        if not CodeEditorFocus.allows_application_shortcuts():
            return False
        self._actions[sequence]()
        return True


class ShortcutLifecycle(Generic[ConfigT]):
    """Project key sequences from a config onto menu actions and application commands.

    Bindings read their key from the config through ``key_from_config``; ``apply``
    validates every sequence, rejects duplicates and then rebinds all of them.
    """

    def __init__(self, application: QApplication) -> None:
        self._application = application
        self._menu_actions: list[tuple[Callable[[ConfigT], str], QAction]] = []
        self._commands: list[
            tuple[
                Callable[[ConfigT], str],
                str,
                Callable[[], None],
            ]
        ] = []
        self._event_filter = ApplicationShortcutFilter({})
        self._application.installEventFilter(self._event_filter)

    def bind_menu_action(
        self,
        key_from_config: Callable[[ConfigT], str],
        action: QAction,
    ) -> None:
        """Bind one concrete action to a typed configuration projection."""

        self._menu_actions.append((key_from_config, action))

    def bind_command(
        self,
        key_from_config: Callable[[ConfigT], str],
        label: str,
        command: Callable[[], None],
    ) -> None:
        """Bind one application-wide command to a typed config projection."""

        self._commands.append((key_from_config, label, command))

    def apply(self, config: ConfigT) -> None:
        """Validate and atomically project all configured key sequences."""

        projected_menu = tuple(
            (
                action,
                self._validated_sequence(
                    action.text().replace("&", ""),
                    key_from_config(config),
                ),
            )
            for key_from_config, action in self._menu_actions
        )
        projected_commands = tuple(
            (
                command,
                self._validated_sequence(label, key_from_config(config)),
            )
            for key_from_config, label, command in self._commands
        )
        normalized = tuple(
            sequence.toString(QKeySequence.SequenceFormat.PortableText)
            for _consumer, sequence in (*projected_menu, *projected_commands)
        )
        if len(set(normalized)) != len(normalized):
            raise ValueError("Application keyboard shortcuts must be unique.")

        for action, sequence in projected_menu:
            action.setShortcut(sequence)
        self._event_filter.replace_actions(
            {
                sequence.toString(QKeySequence.SequenceFormat.PortableText): command
                for command, sequence in projected_commands
            }
        )

    def close(self) -> None:
        self._application.removeEventFilter(self._event_filter)
        self._menu_actions.clear()
        self._commands.clear()

    @staticmethod
    def _validated_sequence(field_name: str, value: str) -> QKeySequence:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Shortcut {field_name} must be a non-empty key sequence.")
        sequence = QKeySequence(value)
        if sequence.isEmpty():
            raise ValueError(f"Shortcut {field_name} is not a valid Qt key sequence.")
        return sequence
