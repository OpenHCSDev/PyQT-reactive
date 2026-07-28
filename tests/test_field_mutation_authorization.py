from __future__ import annotations

from types import SimpleNamespace

import pytest

from pyqt_reactive.services.field_change_dispatcher import (
    FieldChangeEvent,
    FieldDispatchContext,
    SourceStateUpdateStage,
)


class RecordingState:
    def __init__(self) -> None:
        self.writes: list[tuple[str, object]] = []

    def update_parameter(self, path: str, value: object) -> set[str]:
        self.writes.append((path, value))
        return {path}


def test_field_mutation_authorization_precedes_object_state_write() -> None:
    state = RecordingState()
    source = SimpleNamespace(
        before_mutation=lambda: (_ for _ in ()).throw(RuntimeError("mutation rejected")),
        state=state,
        sync_after_model_field_change=lambda *args, **kwargs: None,
    )
    event = FieldChangeEvent(
        field_name="threshold",
        value=5,
        source_manager=source,
    )
    context = FieldDispatchContext(
        event=event,
        source=source,
        root=source,
        source_path="threshold",
        root_path="threshold",
    )

    with pytest.raises(RuntimeError, match="mutation rejected"):
        SourceStateUpdateStage().run(context)

    assert state.writes == []
