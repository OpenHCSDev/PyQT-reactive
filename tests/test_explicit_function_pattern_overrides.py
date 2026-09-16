"""Explicit function overrides survive projection of normally hidden parameters."""

from dataclasses import dataclass

from objectstate import ObjectState, ObjectStateRegistry, config
from python_introspect import parameter_exclusions, set_parameter_exclusions

from pyqt_reactive.services.function_pattern_code_document import (
    EditableFunctionPatternCallable,
    FunctionPatternCodeDocumentService,
    FunctionPatternValue,
)


def test_explicit_override_is_editable_without_exposing_other_runtime_parameters(monkeypatch):
    @dataclass
    class RootConfig:
        pass

    monkeypatch.setattr(config, "_base_config_type", RootConfig)
    def process(image, *, policy: float = 1.0, runtime_context=None):
        return image

    set_parameter_exclusions(process, ("policy", "runtime_context"))
    kwargs = {"policy": 2.0}
    editable = EditableFunctionPatternCallable.for_entry(process, kwargs)
    assert parameter_exclusions(editable) == frozenset({"runtime_context"})
    state = ObjectState(
        object_instance=editable,
        scope_id="explicit-function-override",
        exclude_params=FunctionPatternCodeDocumentService.reserved_parameter_names(editable),
        initial_values=kwargs,
    )
    assert FunctionPatternCodeDocumentService.reconstruct_kwargs_from_state(state) == kwargs
    assert EditableFunctionPatternCallable.for_entry(process, {}) is process
    assert parameter_exclusions(process) == frozenset({"policy", "runtime_context"})


def test_existing_function_state_rebuilds_when_explicit_kwargs_change_surface(monkeypatch):
    @dataclass
    class RootConfig:
        pass

    monkeypatch.setattr(config, "_base_config_type", RootConfig)

    def process(image):
        return image

    parent = ObjectState(object_instance=RootConfig(), scope_id="pattern-parent")
    state = FunctionPatternCodeDocumentService.create_function_state(
        scope_id="pattern-parent::func_0",
        parent_state=parent,
        entry=FunctionPatternValue(process, {}),
    )
    ObjectStateRegistry.register(parent, _skip_snapshot=True)
    ObjectStateRegistry.register(state, _skip_snapshot=True)

    added = FunctionPatternCodeDocumentService.synchronize_existing_function_state(
        state=state,
        parent_state=parent,
        entry=FunctionPatternValue(process, {"artifact_name": "Nuclei"}),
    )
    assert added is not state
    assert FunctionPatternCodeDocumentService.reconstruct_kwargs_from_state(added) == {
        "artifact_name": "Nuclei"
    }

    updated = FunctionPatternCodeDocumentService.synchronize_existing_function_state(
        state=added,
        parent_state=parent,
        entry=FunctionPatternValue(process, {"artifact_name": "Cytoplasm"}),
    )
    assert updated is added
    assert FunctionPatternCodeDocumentService.reconstruct_kwargs_from_state(updated) == {
        "artifact_name": "Cytoplasm"
    }

    removed = FunctionPatternCodeDocumentService.synchronize_existing_function_state(
        state=updated,
        parent_state=parent,
        entry=FunctionPatternValue(process, {}),
    )
    assert removed is not updated
    assert FunctionPatternCodeDocumentService.reconstruct_kwargs_from_state(removed) == {}
