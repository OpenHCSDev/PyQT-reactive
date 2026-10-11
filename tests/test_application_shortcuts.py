"""Shortcut lifecycles project a config's key sequences onto actions and commands."""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QAction, QKeyEvent

from pyqt_reactive.services.application_shortcuts import ShortcutLifecycle


@dataclass(frozen=True)
class Keys:
    open_list: str = "Ctrl+L"
    open_editor: str = "Ctrl+E"
    step_back: str = "Ctrl+Z"


def test_lifecycle_rebinds_live_qactions(qapp) -> None:
    action = QAction("List")
    lifecycle = ShortcutLifecycle[Keys](qapp)
    lifecycle.bind_menu_action(lambda config: config.open_list, action)

    try:
        lifecycle.apply(replace(Keys(), open_list="Ctrl+1"))
        assert action.shortcut().toString() == "Ctrl+1"

        lifecycle.apply(replace(Keys(), open_list="Alt+2"))
        assert action.shortcut().toString() == "Alt+2"
    finally:
        lifecycle.close()


def test_lifecycle_rejects_duplicates_before_rebinding(qapp) -> None:
    first = QAction("First")
    second = QAction("Second")
    lifecycle = ShortcutLifecycle[Keys](qapp)
    lifecycle.bind_menu_action(lambda config: config.open_list, first)
    lifecycle.bind_menu_action(lambda config: config.open_editor, second)
    lifecycle.apply(Keys())
    original = (first.shortcut().toString(), second.shortcut().toString())

    try:
        with pytest.raises(ValueError, match="must be unique"):
            lifecycle.apply(replace(Keys(), open_list="Ctrl+1", open_editor="Ctrl+1"))

        assert (first.shortcut().toString(), second.shortcut().toString()) == original
    finally:
        lifecycle.close()


def test_application_command_accepts_any_configured_qt_key(qapp) -> None:
    calls: list[str] = []
    lifecycle = ShortcutLifecycle[Keys](qapp)
    lifecycle.bind_command(lambda config: config.step_back, "Back", lambda: calls.append("back"))

    try:
        lifecycle.apply(replace(Keys(), step_back="Ctrl+B"))
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)

        assert lifecycle._event_filter.eventFilter(None, event) is True
        assert calls == ["back"]
    finally:
        lifecycle.close()
