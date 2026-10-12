"""A tabbed editor window hosts whatever tab family its edited object declares."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QLabel, QMessageBox

from pyqt_reactive.forms.parameter_form_manager import FormManagerConfig, ParameterFormManager
from pyqt_reactive.services.window_navigation import (
    FieldWindowNavigationDriver,
    NavigationTargetClaimedTwiceError,
    NavigationWaitReason,
    RegisteredWindowNavigationReadiness,
    RegisteredWindowNavigationRequest,
)
from pyqt_reactive.widgets.shared.action_tabbed_window_body import ActionTabMaterialization
from pyqt_reactive.windows.tabbed_editor_window import (
    EditedObject,
    EditorTab,
    SaveRefused,
    TabbedEditorNavigationDriver,
    TabbedEditorWindow,
)

SCOPE = "/note"


@dataclass(frozen=True)
class Note:
    """A throwaway editable object."""

    text: str = "hello"
    count: int = 1


class NoteTab(EditorTab):
    """The tab family of the throwaway note editor."""


class NoteFieldsTab(NoteTab):
    label = "Fields"

    def build(self) -> ActionTabMaterialization:
        self.form_manager = ParameterFormManager(
            state=self.window.edited.state,
            config=FormManagerConfig(parent=self.window, color_scheme=self.window.color_scheme),
        )
        return ActionTabMaterialization(self.form_manager)

    def form_managers(self):
        return (self.form_manager,)

    def navigation_driver(self):
        self.visited: list[str] = []
        return FieldWindowNavigationDriver(self.visited.append, self.form_manager.owns_field_path)


class NoteSummaryTab(NoteTab):
    label = "Summary"

    def build(self) -> ActionTabMaterialization:
        self.summary = QLabel()
        self.visited: list[str] = []
        self.refresh_from_state()
        return ActionTabMaterialization(self.summary)

    def refresh_from_state(self) -> None:
        values = self.window.edited.state.get_current_values()
        self.summary.setText(f"{values['text']} x{values['count']}")

    def navigation_driver(self):
        return FieldWindowNavigationDriver(self.visited.append, self.owns_field_path)

    def owns_field_path(self, field_path: str) -> bool:
        return field_path.startswith("summary")


class NoteEdit(EditedObject):
    tab_family = NoteTab

    def __init__(self, state: ObjectState) -> None:
        self._state = state
        self.saved: list[Note] = []

    @property
    def scope_id(self) -> str:
        return self._state.scope_id

    @property
    def state(self) -> ObjectState:
        return self._state

    def title(self) -> str:
        return "Edit Note"

    def save(self) -> Note:
        note = self._state.to_object()
        if not note.text:
            raise SaveRefused("Text cannot be empty.")
        self.saved.append(note)
        return note


@pytest.fixture(autouse=True)
def _clear_registry():
    set_base_config_type(Note)
    ObjectStateRegistry.clear()
    yield
    ObjectStateRegistry.clear()


@pytest.fixture
def note_window(qapp):
    state = ObjectState(Note(), scope_id=SCOPE)
    ObjectStateRegistry.register(state, _skip_snapshot=True)
    window = TabbedEditorWindow(NoteEdit(state))
    qapp.processEvents()
    yield window
    window._cleanup_managed_resources()
    window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _tab_labels(window: TabbedEditorWindow) -> list[str]:
    bar = window.tab_body.tab_bar
    return [bar.tabText(index) for index in range(bar.count())]


def test_window_hosts_the_declared_family_in_declaration_order(note_window) -> None:
    assert _tab_labels(note_window) == ["Fields", "Summary"]
    assert [type(tab) for tab in note_window.tabs] == [NoteFieldsTab, NoteSummaryTab]
    assert note_window.windowTitle() == "Edit Note"
    assert not note_window.save_button.isEnabled()
    assert note_window.form_managers() == (note_window.tab(NoteFieldsTab).form_manager,)


def test_a_new_object_and_a_new_tab_are_hosted_without_touching_the_window(qapp) -> None:
    """A throwaway editable object with its own tab family, then one more tab."""

    class ScratchTab(EditorTab):
        pass

    class ScratchEdit(NoteEdit):
        tab_family = ScratchTab

        def title(self) -> str:
            return "Scratch"

    class ScratchTextTab(ScratchTab):
        label = "Text"

        def build(self) -> ActionTabMaterialization:
            return ActionTabMaterialization(QLabel("text"))

    def open_window() -> TabbedEditorWindow:
        ObjectStateRegistry.clear()
        state = ObjectState(Note(), scope_id=SCOPE)
        ObjectStateRegistry.register(state, _skip_snapshot=True)
        return TabbedEditorWindow(ScratchEdit(state))

    first = open_window()
    assert _tab_labels(first) == ["Text"]
    assert first.windowTitle() == "Scratch"
    first._cleanup_managed_resources()

    class ScratchHistoryTab(ScratchTab):
        label = "History"

        def build(self) -> ActionTabMaterialization:
            return ActionTabMaterialization(QLabel("no history"))

    second = open_window()
    try:
        assert _tab_labels(second) == ["Text", "History"]
        second.tab(ScratchHistoryTab).select()
        assert second.tab_body.current_widget().text() == "no history"
    finally:
        second._cleanup_managed_resources()
        first.deleteLater()
        second.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_edit_marks_dirty_and_save_commits_the_edited_object(note_window, qapp) -> None:
    saved: list[object] = []
    note_window.saved.connect(saved.append)

    note_window.state.update_parameter("count", 5)
    qapp.processEvents()

    assert note_window.windowTitle() == "* Edit Note"
    assert note_window.save_button.isEnabled()
    assert note_window.tab(NoteSummaryTab).summary.text() == "hello x1"

    note_window.save_managed_window(close_window=False)

    assert saved == [Note(count=5)] == note_window.edited.saved
    assert note_window.windowTitle() == "Edit Note"
    assert not note_window.save_button.isEnabled()


def test_refused_save_tells_the_user_and_keeps_the_edit(note_window, monkeypatch) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _parent, _title, text: warnings.append(text)
    )
    note_window.state.update_parameter("text", "")

    note_window.save_managed_window()

    assert warnings == ["Text cannot be empty."]
    assert note_window.edited.saved == []
    assert note_window.state.is_raw_dirty


def test_time_travel_and_tab_edits_redraw_the_other_tabs(note_window, qapp) -> None:
    summary = note_window.tab(NoteSummaryTab)
    note_window.state.update_parameter("count", 3)

    note_window.tab_edited_state(note_window.tab(NoteFieldsTab))

    assert summary.summary.text() == "hello x3"


def test_navigation_shows_the_tab_whose_driver_owns_the_field(note_window) -> None:
    driver = note_window.window_navigation_driver()
    request = RegisteredWindowNavigationRequest(
        window=note_window, requested_scope_id=SCOPE, field_path="summary.total"
    )
    summary = note_window.tab(NoteSummaryTab)

    assert driver.accepts(request)
    assert driver.owning_tabs(request) == (summary,)
    driver.prepare(request)
    driver.execute(request)

    assert note_window.tab_body.current_index() == note_window.tabs.index(summary)
    assert summary.visited == ["summary.total"]

    # The form shows no ``summary`` field, so it never claimed the path.
    fields = note_window.tab(NoteFieldsTab)
    assert fields.visited == []
    elsewhere = RegisteredWindowNavigationRequest(
        window=note_window, requested_scope_id=SCOPE, field_path="text"
    )
    assert driver.owning_tabs(elsewhere) == (fields,)
    driver.execute(elsewhere)
    assert fields.visited == ["text"]
    assert summary.visited == ["summary.total"]


def test_two_tabs_claiming_one_field_path_is_a_declaration_error(note_window) -> None:
    """No tab wins by position: an overlap is refused, naming both claimants."""

    fields, summary = note_window.tabs
    summary.owns_field_path = lambda field_path: True
    driver = TabbedEditorNavigationDriver(note_window.tabs)
    claimed_twice = RegisteredWindowNavigationRequest(
        window=note_window, requested_scope_id=SCOPE, field_path="text"
    )

    with pytest.raises(NavigationTargetClaimedTwiceError, match="'text' is claimed by 2 owners"):
        driver.accepts_field_path(claimed_twice)
    with pytest.raises(NavigationTargetClaimedTwiceError):
        driver.owning_tabs(claimed_twice)
    assert fields.visited == []
    assert summary.visited == []

    shown_by_nobody = RegisteredWindowNavigationRequest(
        window=note_window, requested_scope_id=SCOPE, field_path="absent"
    )
    summary.owns_field_path = lambda field_path: False
    assert not TabbedEditorNavigationDriver(note_window.tabs).accepts_field_path(shown_by_nobody)


def test_readiness_and_its_callbacks_come_from_the_owning_tab_only(note_window) -> None:
    class Waiting(FieldWindowNavigationDriver):
        def __init__(self, owns_field_path) -> None:
            super().__init__(lambda _path: None, owns_field_path)
            self.callbacks: list[object] = []

        def readiness(self, request):
            return RegisteredWindowNavigationReadiness(
                wait_reason=NavigationWaitReason.FIELD_TARGET
            )

        def register_readiness_callback(self, request, callback) -> bool:
            self.callbacks.append(callback)
            return True

    fields, summary = note_window.tabs
    general = Waiting(fields.form_manager.owns_field_path)
    fields.navigation_driver = lambda: general
    driver = TabbedEditorNavigationDriver(note_window.tabs)

    def retry() -> None:
        pass

    owned_by_fields = RegisteredWindowNavigationRequest(
        window=note_window, requested_scope_id=SCOPE, field_path="text"
    )
    owned_by_summary = RegisteredWindowNavigationRequest(
        window=note_window, requested_scope_id=SCOPE, field_path="summary.total"
    )

    assert driver.readiness(owned_by_fields).wait_reason is NavigationWaitReason.FIELD_TARGET
    assert driver.register_readiness_callback(owned_by_fields, retry)
    assert general.callbacks == [retry]

    assert not driver.readiness(owned_by_summary).needs_wait
    assert not driver.register_readiness_callback(owned_by_summary, retry)
    assert general.callbacks == [retry]


def test_cancel_restores_the_saved_state(note_window) -> None:
    cancelled: list[bool] = []
    note_window.cancelled.connect(lambda: cancelled.append(True))
    note_window.state.update_parameter("count", 9)

    note_window.reject()

    assert cancelled == [True]
    assert note_window.state.get_current_values()["count"] == 1
