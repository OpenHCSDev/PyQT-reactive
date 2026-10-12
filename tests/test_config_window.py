"""A config window edits ObjectState configs and renders them in the application's format."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from objectstate import (
    LazyDataclassFactory,
    ObjectState,
    ObjectStateRegistry,
    get_live_global_config,
    get_saved_global_config,
    mark_global_config_type,
    set_base_config_type,
)
from PyQt6.QtWidgets import QMessageBox

from pyqt_reactive.windows.config_window import (
    ConfigDocumentFormat,
    ConfigSaveParticipant,
    ConfigWindow,
    ConfigWindowTabSpec,
)


@dataclass(frozen=True)
class Settings:
    count: int = 1


class LineFormat(ConfigDocumentFormat):
    """``count=<n>`` per document."""

    def render(self, config, *, expected_config_type, clean_mode=True) -> str:
        assert isinstance(config, expected_config_type)
        return f"count={config.count}"

    def from_source(self, source: str, *, expected_config_type):
        return expected_config_type(count=int(source.split("=", 1)[1]))


class SettingsWindow(ConfigWindow):
    document_format = LineFormat()


@pytest.fixture(autouse=True)
def _clear_registry():
    set_base_config_type(Settings)
    ObjectStateRegistry.clear()
    yield
    ObjectStateRegistry.clear()


def test_view_code_and_save_go_through_the_declared_format_and_participant(qapp) -> None:
    state = ObjectState(Settings(count=2), scope_id="/settings")
    ObjectStateRegistry.register(state, _skip_snapshot=True)
    saved: list[object] = []
    window = SettingsWindow(
        tabs=(
            ConfigWindowTabSpec(
                state=state,
                save_participant=ConfigSaveParticipant(
                    apply=saved.append, rollback=lambda _c: None
                ),
            ),
        ),
        scope_id="/settings",
    )
    try:
        qapp.processEvents()
        driver = window.window_code_document_driver()
        assert driver.read_document().source == "count=2"

        driver.apply_source("count=7")
        window.save_config()

        assert [config.count for config in saved] == [7]
        assert state.saved_object.count == 7
    finally:
        window.before_managed_close()
        window.deleteLater()
        qapp.processEvents()


# --- The global config through the window ---------------------------------------
# The state registered at the global scope holds the global config (ObjectState 4),
# so the window keeps nothing beside it: a code edit, a cancel, a save and a failed
# save move the live and the saved global config, and a descendant, with the state.


@dataclass(frozen=True)
class Policy:
    count: int | None = None


@dataclass(frozen=True)
class GlobalSettings:
    policy: Policy = field(default_factory=lambda: Policy(count=1))


mark_global_config_type(GlobalSettings)
LazyPolicy = LazyDataclassFactory.make_lazy_simple(Policy)


@dataclass
class Plate:
    policy: LazyPolicy = field(default_factory=LazyPolicy)


class GlobalSettingsFormat(ConfigDocumentFormat):
    def render(self, config, *, expected_config_type, clean_mode=True) -> str:
        return f"count={config.policy.count}"

    def from_source(self, source: str, *, expected_config_type):
        return expected_config_type(policy=Policy(count=int(source.split("=", 1)[1])))


class GlobalSettingsWindow(ConfigWindow):
    document_format = GlobalSettingsFormat()


def test_global_config_follows_the_window_through_edit_cancel_save_and_failed_save(
    qapp, monkeypatch
) -> None:
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: None)
    set_base_config_type(GlobalSettings)
    global_state = ObjectState(GlobalSettings(), scope_id="")
    plate = ObjectState(Plate(), scope_id="/plate")
    for state in (global_state, plate):
        ObjectStateRegistry.register(state, _skip_snapshot=True)
    applied: list[int] = []

    def apply(config: GlobalSettings) -> None:
        if config.policy.count == 13:
            raise RuntimeError("refused")
        applied.append(config.policy.count)

    def seen() -> tuple:
        """Live and saved: the global config, then what the plate inherits."""
        return (
            get_live_global_config(GlobalSettings).policy.count,
            get_saved_global_config(GlobalSettings).policy.count,
            plate.get_resolved_value("policy.count"),
            plate.get_saved_resolved_value("policy.count"),
        )

    window = GlobalSettingsWindow(
        tabs=(
            ConfigWindowTabSpec(
                state=global_state,
                save_participant=ConfigSaveParticipant(apply=apply, rollback=lambda _c: None),
            ),
        ),
        scope_id="",
    )
    try:
        qapp.processEvents()
        driver = window.window_code_document_driver()
        assert seen() == (1, 1, 1, 1)

        driver.apply_source("count=5")  # an unsaved code edit
        assert seen() == (5, 1, 5, 1)

        window.restore_managed_state()  # cancel
        assert seen() == (1, 1, 1, 1)

        driver.apply_source("count=13")
        window.save_config(close_window=False)  # the participant refuses
        assert seen() == (13, 1, 13, 1) and applied == []

        driver.apply_source("count=7")
        window.save_config(close_window=False)
        assert seen() == (7, 7, 7, 7) and applied == [7]
    finally:
        window.before_managed_close()
        window.deleteLater()
        qapp.processEvents()
