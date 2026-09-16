from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
from types import SimpleNamespace

import pytest
from objectstate.object_state_registry import ObjectStateRegistry

from pyqt_reactive.services.function_pattern_code_document import (
    FunctionPatternCodeDocumentService,
)
from pyqt_reactive.services.scope_token_service import (
    ScopeTokenService,
    ScopeTokenTarget,
    reconcile_occurrence_tokens,
)
from pyqt_reactive.widgets.function_list_editor import (
    FunctionListEditorAction,
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


def alternate_function(image, radius: int = 1):
    return image


def test_function_editor_actions_own_labels_and_execution_leaves() -> None:
    calls: list[object] = []
    widget = SimpleNamespace(
        add_function=lambda: calls.append(FunctionListEditorAction.ADD),
        edit_function_code=lambda: calls.append(FunctionListEditorAction.CODE),
        show_component_selection_dialog=lambda: calls.append(
            FunctionListEditorAction.COMPONENT
        ),
        _navigate_pattern_key=lambda direction: calls.append(direction),
    )

    for action in FunctionListEditorAction:
        action.invoke(widget)

    assert calls == [
        FunctionListEditorAction.ADD,
        FunctionListEditorAction.CODE,
        FunctionListEditorAction.COMPONENT,
        -1,
        1,
    ]
    assert FunctionListEditorAction.ADD.label == "Add"
    assert (
        FunctionListEditorAction.ADD.object_name
        == "function_list_editor_action_add"
    )


def _wrapped(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


@dataclass
class RegisteredFunctionState:
    scope_id: str
    object_instance: object


class AmbiguousEquality:
    def __eq__(self, other: object):
        del other
        return self

    def __bool__(self) -> bool:
        raise ValueError("ambiguous")


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


def test_complete_pattern_reconciliation_preserves_tokens_across_reorder_and_edit() -> None:
    service = FunctionPatternCodeDocumentService()

    tokens = service.reconcile_pattern_tokens(
        [
            (sample_function, {"threshold": 1}),
            (alternate_function, {"radius": 2}),
        ],
        ["func_4", "func_7"],
        [
            (alternate_function, {"radius": 2}),
            (sample_function, {"threshold": 3}),
        ],
    )

    assert tokens == ["func_7", "func_4"]


def test_complete_pattern_reconciliation_does_not_guess_between_duplicates() -> None:
    service = FunctionPatternCodeDocumentService()

    tokens = service.reconcile_pattern_tokens(
        [
            (sample_function, {"threshold": 1}),
            (sample_function, {"threshold": 2}),
        ],
        ["func_4", "func_7"],
        [
            (sample_function, {"threshold": 3}),
            (sample_function, {"threshold": 4}),
        ],
    )

    assert set(tokens).isdisjoint({"func_4", "func_7"})
    assert len(set(tokens)) == 2


def test_complete_pattern_reconciliation_preserves_wrapped_default_occurrences() -> None:
    service = FunctionPatternCodeDocumentService()

    tokens = service.reconcile_pattern_tokens(
        [
            (_wrapped(sample_function), {"threshold": 1}),
            (_wrapped(sample_function), {"threshold": 1}),
        ],
        ["func_4", "func_7"],
        [sample_function, sample_function],
    )

    assert tokens == ["func_4", "func_7"]


def test_complete_pattern_reconciliation_handles_ambiguous_kwargs_equality() -> None:
    service = FunctionPatternCodeDocumentService()

    tokens = service.reconcile_pattern_tokens(
        [(sample_function, {"threshold": AmbiguousEquality()})],
        ["func_4"],
        [(sample_function, {"threshold": AmbiguousEquality()})],
    )

    assert tokens == ["func_4"]


def test_occurrence_reconciliation_keeps_a_new_explicit_token() -> None:
    new_entry = (sample_function, {"threshold": 1})

    tokens = reconcile_occurrence_tokens(
        [],
        [],
        [new_entry],
        same_declaration=lambda left, right: left == right,
        occurrence_authorities=lambda entry: (entry[0],),
        token_factory=lambda: "func_8",
        requested_tokens=["func_4"],
    )

    assert tokens == ["func_4"]


def test_adopting_a_token_invalidates_the_projected_scope_id() -> None:
    target = SimpleNamespace(_scope_token="step_1")

    assert ScopeTokenService.build_scope_id("plate", target) == "plate::step_1"

    ScopeTokenService.adopt_token("plate", target, "step_7")

    assert ScopeTokenService.build_scope_id("plate", target) == "plate::step_7"


@pytest.mark.parametrize("already_registered", (False, True))
def test_restoring_detached_token_does_not_register_or_seed_live_state(monkeypatch, already_registered):
    @dataclass
    class Step(ScopeTokenTarget):
        number: int = 3

    monkeypatch.setattr(ScopeTokenService, "_generators", {})
    monkeypatch.setattr(ScopeTokenService, "_scope_id_cache", {})
    live = Step()
    if already_registered:
        ScopeTokenService.build_scope_id("plate", live)
    generators_before = dict(ScopeTokenService._generators)
    cache_before = dict(ScopeTokenService._scope_id_cache)
    generator_values_before = {
        key: (generator._counter, set(generator._used_tokens))
        for key, generator in generators_before.items()
    }
    detached = Step(99)
    attributes_before = vars(detached).copy()

    assert ScopeTokenService.restore_object_token(detached, "step_7") == "step_7"
    assert vars(detached) == attributes_before | {ScopeTokenService.SCOPE_TOKEN_ATTRIBUTE: "step_7"}
    assert ScopeTokenService.object_token(detached) == "step_7"
    assert ScopeTokenService._generators == generators_before
    assert ScopeTokenService._scope_id_cache == cache_before
    assert {
        key: (generator._counter, set(generator._used_tokens))
        for key, generator in ScopeTokenService._generators.items()
    } == generator_values_before

    assert ScopeTokenService.build_scope_id("plate", detached) == "plate::step_7"
    generator = ScopeTokenService.get_generator("plate", "step")
    assert "step_7" in generator._used_tokens
    assert ScopeTokenService.build_scope_id("plate", Step()) == "plate::step_8"


def test_scope_token_consumers_derive_the_single_attribute_declaration(monkeypatch):
    @dataclass
    class Step(ScopeTokenTarget):
        number: int = 3

    monkeypatch.setattr(ScopeTokenService, "_generators", {})
    monkeypatch.setattr(ScopeTokenService, "_scope_id_cache", {})
    monkeypatch.setattr(ScopeTokenService, "SCOPE_TOKEN_ATTRIBUTE", "_alternative_token")
    target = Step()
    ScopeTokenService.restore_object_token(target, "step_2")
    assert ScopeTokenService.object_token(target) == "step_2"
    assert ScopeTokenService.build_scope_id("plate", target) == "plate::step_2"
    ScopeTokenService.adopt_token("plate", target, "step_9")
    assert ScopeTokenService.object_token(target) == "step_9"
    assert ScopeTokenService.build_scope_id("plate", target) == "plate::step_9"
    assert vars(target) == {"number": 3, "_alternative_token": "step_9"}


def test_native_reused_object_id_does_not_override_restored_token(monkeypatch):
    @dataclass
    class Step(ScopeTokenTarget):
        number: int = 3

    monkeypatch.setattr(ScopeTokenService, "_generators", {})
    monkeypatch.setattr(ScopeTokenService, "_scope_id_cache", {})
    previous = Step()
    assert ScopeTokenService.build_scope_id("plate", previous) == "plate::step_0"
    departed_id = id(previous)
    del previous
    detached = Step(99)
    assert id(detached) == departed_id, "Native CPython reproduction must actually reuse the departed ID"
    generator = ScopeTokenService.get_generator("plate", "step")
    counter_before = generator._counter
    cache_before = dict(ScopeTokenService._scope_id_cache)
    ScopeTokenService.restore_object_token(detached, "step_7")
    assert generator._counter == counter_before
    assert ScopeTokenService._scope_id_cache == cache_before
    assert ScopeTokenService.build_scope_id("plate", detached) == "plate::step_7"
    assert generator._counter == 8


def test_cached_numeric_id_without_a_current_token_is_not_identity(monkeypatch):
    @dataclass
    class Step(ScopeTokenTarget):
        number: int = 3

    monkeypatch.setattr(ScopeTokenService, "_generators", {})
    target = Step()
    monkeypatch.setattr(ScopeTokenService, "_scope_id_cache", {("plate", id(target)): "plate::foreign_9"})
    assert ScopeTokenService.build_scope_id("plate", target) == "plate::step_0"
    assert ScopeTokenService.object_token(target) == "step_0"


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
