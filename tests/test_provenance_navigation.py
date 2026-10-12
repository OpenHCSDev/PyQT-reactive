"""A label goes to the field that supplies its inherited value.

The source is the state's ``get_provenance`` answer. When another config of the
same object supplies the value, the source state is the label's own state,
with or without a scope id.
"""

from dataclasses import dataclass, field

import objectstate.config as config_module
import pytest
from objectstate import (
    LazyDataclassFactory,
    ObjectState,
    ObjectStateRegistry,
    mark_global_config_type,
    set_base_config_type,
    set_global_config_for_editing,
)

from pyqt_reactive.services.scope_window_navigation import ScopeWindowNavigationService
from pyqt_reactive.widgets.shared.clickable_help_components import ProvenanceLabel


@dataclass
class SourceFilterConfig:
    well_filter: int | None = None


@dataclass
class SourcePathConfig(SourceFilterConfig):
    suffix: str | None = None


@dataclass
class SourceGlobalConfig:
    filter_config: SourceFilterConfig = field(default_factory=SourceFilterConfig)
    path_config: SourcePathConfig = field(default_factory=SourcePathConfig)


mark_global_config_type(SourceGlobalConfig)
LazySourceFilterConfig = LazyDataclassFactory.make_lazy_simple(SourceFilterConfig)
LazySourcePathConfig = LazyDataclassFactory.make_lazy_simple(SourcePathConfig)

OWN = "path_config.well_filter"
SIBLING = "filter_config.well_filter"


@dataclass
class SourcePipeline:
    filter_config: LazySourceFilterConfig = field(default_factory=LazySourceFilterConfig)
    path_config: LazySourcePathConfig = field(default_factory=LazySourcePathConfig)


@pytest.fixture(params=[None, "plate"], ids=["no scope id", "scope id"])
def label(qapp, request, monkeypatch):
    previous_base = config_module._base_config_type
    ObjectStateRegistry.clear()
    set_base_config_type(SourceGlobalConfig)
    set_global_config_for_editing(
        SourceGlobalConfig, SourceGlobalConfig(SourceFilterConfig(well_filter=1))
    )
    state = ObjectState(SourcePipeline(), scope_id=request.param)
    label = ProvenanceLabel("well filter", state=state, dotted_path=OWN)
    label.scrolled_to = []
    label.window_requests = []
    monkeypatch.setattr(label, "_scroll_within_current_window", label.scrolled_to.append)
    monkeypatch.setattr(
        ScopeWindowNavigationService,
        "navigate",
        lambda request: label.window_requests.append(request) or request,
    )
    try:
        yield label
    finally:
        label.deleteLater()
        ObjectStateRegistry.clear()
        config_module._base_config_type = previous_base


def test_value_from_a_sibling_config_scrolls_this_window_to_the_sibling_field(label):
    label._state.update_parameter(SIBLING, 7)

    assert label._state.get_resolved_value(OWN) == 7
    assert label._provenance_source() == (label._state.scope_id, SourceFilterConfig)
    assert label._navigate_to_provenance_source() is True
    assert label.scrolled_to == [SIBLING]
    assert label.window_requests == []


def test_value_set_on_the_field_has_no_source_to_go_to(label):
    label._state.update_parameter(OWN, 9)

    assert label._has_provenance() is False
    assert label._navigate_to_provenance_source() is False
    assert label.scrolled_to == []
    assert label.window_requests == []
