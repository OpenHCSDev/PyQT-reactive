"""Time-travel commands, history views and post-restore navigation."""

from __future__ import annotations

from objectstate import ObjectStateRegistry, ScopeKey
from PyQt6.QtCore import QTimer

from pyqt_reactive.services.time_travel_navigation import (
    FieldPathTarget,
    FunctionScopeRef,
    FunctionTokenTarget,
    TimeTravelNavigator,
)
from pyqt_reactive.widgets.shared.abstract_table_browser import TableSelectionMode
from pyqt_reactive.widgets.time_travel import TimeTravelCommands


def _function_child(scope_id: str) -> FunctionScopeRef | None:
    scope = ScopeKey(scope_id)
    if scope.depth == 3 and scope.parts[1].startswith("editor"):
        return FunctionScopeRef(owner_scope_id=scope.parent, function_token=scope.last)
    return None


NAVIGATOR = TimeTravelNavigator(function_scope=_function_child)


def test_navigation_follows_only_the_triggering_edit() -> None:
    editor = "/root::editor_1"
    function = f"{editor}::fn_0"

    assert NAVIGATOR.includes("/root::editor_9", None)
    assert NAVIGATOR.includes(editor, editor)
    assert not NAVIGATOR.includes(function, editor)
    assert not NAVIGATOR.includes("/root::editor_9", editor)
    assert NAVIGATOR.includes(function, function)
    assert NAVIGATOR.includes(editor, function)
    assert not NAVIGATOR.includes("/root::editor_1", "/root")


def test_field_target_replaces_stale_function_target() -> None:
    field = FieldPathTarget("settings.source")
    function = FunctionTokenTarget("fn_0")

    assert field.replaces(function)
    assert not function.replaces(field)
    assert function.replaces(None)


def test_navigation_runs_after_refreshes_queued_in_the_same_turn(monkeypatch) -> None:
    callbacks: list[object] = []

    def fake_single_shot(delay, callback) -> None:
        assert delay == 0
        callbacks.append(callback)

    monkeypatch.setattr(QTimer, "singleShot", staticmethod(fake_single_shot))
    order: list[str] = []
    TimeTravelNavigator.defer(lambda: order.append("navigate"))
    QTimer.singleShot(0, lambda: order.append("refresh"))

    while callbacks:
        callbacks.pop(0)()

    assert order == ["refresh", "navigate"]


def test_refused_restore_neither_runs_nor_refreshes() -> None:
    operations: list[str] = []
    refreshes: list[bool] = []

    def refuse() -> None:
        raise RuntimeError("mutation refused")

    commands = TimeTravelCommands(refresh=lambda: refreshes.append(True), before_restore=refuse)

    assert not commands._run(lambda: operations.append("mutated"))
    assert operations == [] and refreshes == []


def test_history_hides_the_application_scopes(monkeypatch) -> None:
    seen: list[bool] = []

    def history_info(filter_fn):
        seen.extend((filter_fn("visible"), filter_fn("hidden"), filter_fn("")))
        return []

    monkeypatch.setattr(ObjectStateRegistry, "get_history_info", staticmethod(history_info))
    commands = TimeTravelCommands(
        refresh=lambda: None,
        before_restore=lambda: None,
        hidden_scopes=frozenset({"", "hidden"}),
    )

    assert commands.history() == []
    assert seen == [True, False, False]


def test_snapshot_browser_lists_history_in_a_single_selection_table(qapp) -> None:
    from pyqt_reactive.windows.snapshot_browser_window import SnapshotBrowserWindow

    window = SnapshotBrowserWindow(
        commands=TimeTravelCommands(refresh=lambda: None, before_restore=lambda: None)
    )
    try:
        assert window.browser._selection_mode is TableSelectionMode.SINGLE
        assert window.browser.window() is window
        assert "QComboBox::drop-down" not in window.branch_combo.styleSheet()
        assert "QComboBox::drop-down" not in window.timeline_widget.styleSheet()
    finally:
        window.close()
        qapp.processEvents()
