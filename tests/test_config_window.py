"""A config window edits ObjectState configs and renders them in the application's format."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type

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
