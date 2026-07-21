from __future__ import annotations

from dataclasses import dataclass

import pytest

from objectstate.object_state_registry import ObjectStateRegistry
from pyqt_reactive.widgets.function_list_editor import FunctionListEditorWidget


def _reset_registry() -> None:
    ObjectStateRegistry._states.clear()
    ObjectStateRegistry._time_travel_limbo.clear()
    ObjectStateRegistry._graveyard.clear()
    ObjectStateRegistry._snapshots.clear()
    ObjectStateRegistry._timelines.clear()
    ObjectStateRegistry._current_timeline = "main"
    ObjectStateRegistry._current_head = None
    ObjectStateRegistry._in_time_travel = False
    ObjectStateRegistry._atomic_depth = 0
    ObjectStateRegistry._atomic_label = None
    ObjectStateRegistry._atomic_triggering_scope = None


@pytest.fixture(autouse=True)
def isolated_object_state_registry():
    """Keep the direct registry test doubles local to each test."""

    _reset_registry()
    yield
    _reset_registry()


def sample_function(image, threshold: int = 1):
    return image


@dataclass
class RegisteredFunctionState:
    scope_id: str
    object_instance: object


def test_function_editor_reuses_existing_child_scope_token() -> None:
    _reset_registry()

    editor = FunctionListEditorWidget.__new__(FunctionListEditorWidget)
    editor.scope_id = "plate::functionstep_1"

    scope_id = "plate::functionstep_1::cellprofilerruntimecallable_0"
    ObjectStateRegistry._states[scope_id] = RegisteredFunctionState(
        scope_id=scope_id,
        object_instance=sample_function,
    )

    tokens = editor._existing_function_scope_tokens(
        [(sample_function, {"threshold": 3})],
        None,
    )

    assert tokens == ["cellprofilerruntimecallable_0"]


def test_function_editor_replaces_stale_sidecar_scope_token() -> None:
    _reset_registry()

    editor = FunctionListEditorWidget.__new__(FunctionListEditorWidget)
    editor.scope_id = "plate::functionstep_1"

    scope_id = "plate::functionstep_1::cellprofilerruntimecallable_0"
    ObjectStateRegistry._states[scope_id] = RegisteredFunctionState(
        scope_id=scope_id,
        object_instance=sample_function,
    )

    tokens = editor._canonical_function_scope_tokens(
        [(sample_function, {"threshold": 3})],
        None,
        ["func_0"],
    )

    assert tokens == ["cellprofilerruntimecallable_0"]
