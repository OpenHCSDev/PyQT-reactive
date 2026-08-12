from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from objectstate.object_state_registry import ObjectStateRegistry

from pyqt_reactive.services.function_pattern_code_document import (
    FunctionPatternCodeDocumentService,
)
from pyqt_reactive.widgets.function_list_editor import (
    FunctionListEditorWidget,
    PatternMutation,
)


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


def test_function_pattern_tokens_are_unique_per_occurrence() -> None:
    service = FunctionPatternCodeDocumentService()

    tokens = service.tokens_for_pattern(
        {
            "0": [sample_function, sample_function],
            "1": [sample_function],
        }
    )

    assert tokens == {
        "0": ["func_0", "func_1"],
        "1": ["func_2"],
    }


def test_function_pattern_tokens_reuse_existing_occurrence_tokens() -> None:
    service = FunctionPatternCodeDocumentService()

    tokens = service.tokens_for_pattern(
        [sample_function, sample_function],
        ["func_4", "func_7"],
    )

    assert tokens == ["func_4", "func_7"]


def test_pattern_mutation_authorization_runs_before_local_write() -> None:
    editor = FunctionListEditorWidget.__new__(FunctionListEditorWidget)
    values = ["original"]
    editor._before_mutation = lambda: (_ for _ in ()).throw(RuntimeError("mutation rejected"))

    with pytest.raises(RuntimeError, match="mutation rejected"):
        editor._commit_pattern_mutation(
            PatternMutation.refreshed(
                "replace value",
                lambda: values.__setitem__(0, "mutated"),
                lambda: None,
            )
        )

    assert values == ["original"]


def test_parameter_synchronization_does_not_reauthorize_after_form_write() -> None:
    values = ["before"]
    editor = SimpleNamespace(
        _before_mutation=lambda: (_ for _ in ()).throw(
            AssertionError("post-write authorization must not run")
        ),
        _update_pattern_data=lambda: None,
        _emit_pattern_changed=lambda: None,
    )

    FunctionListEditorWidget._commit_pattern_mutation(
        editor,
        PatternMutation.parameter_update(
            lambda: values.__setitem__(0, "after"),
        ),
    )

    assert values == ["after"]


def test_code_pattern_authorization_precedes_atomic_edit() -> None:
    editor = FunctionListEditorWidget.__new__(FunctionListEditorWidget)
    applied: list[object] = []
    editor._before_mutation = lambda: (_ for _ in ()).throw(RuntimeError("mutation rejected"))
    editor._apply_edited_pattern_internal = applied.append

    with pytest.raises(RuntimeError, match="mutation rejected"):
        editor._apply_edited_pattern([(sample_function, {})])

    assert applied == []
