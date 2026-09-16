"""Real parameter forms flash resolved value changes, not reset gestures."""

from dataclasses import dataclass, field

import objectstate.config as config_module
import pytest
from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type
from objectstate.lazy_factory import LazyDataclassFactory
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QDialog, QVBoxLayout

from pyqt_reactive.animation.flash_mixin import WindowFlashOverlay
from pyqt_reactive.flash_trace import FlashTrace
from pyqt_reactive.forms.parameter_form_manager import (
    FormManagerConfig,
    ParameterFormManager,
)
from pyqt_reactive.theming import ColorScheme


@dataclass
class ResetFields:
    number: int = 3
    maybe: int | None = None


@dataclass
class ResetRoot:
    child: ResetFields = field(default_factory=ResetFields)


LazyResetFields = LazyDataclassFactory.make_lazy_simple(ResetFields)


@dataclass
class LazyResetRoot:
    child: LazyResetFields = field(default_factory=LazyResetFields)


def _flush(qapp):
    for _ in range(20):
        qapp.processEvents()


def _queued_leaf_paths() -> set[str]:
    return {
        dict(record.fields)["path"]
        for record in FlashTrace.recent()
        if record.event == "form.leaf_flash.start"
    }


@pytest.fixture
def form(qapp, request):
    root_type = request.param
    previous_base = config_module._base_config_type
    ObjectStateRegistry.clear()
    set_base_config_type(root_type)
    host = QDialog()
    manager = ParameterFormManager(
        ObjectState(root_type()),
        FormManagerConfig(color_scheme=ColorScheme(), use_scroll_area=False),
    )
    QVBoxLayout(host).addWidget(manager)
    host.show()
    _flush(qapp)
    try:
        yield manager
    finally:
        WindowFlashOverlay.cleanup_window(host)
        host.close()
        manager.deleteLater()
        host.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        _flush(qapp)
        ObjectStateRegistry.clear()
        config_module._base_config_type = previous_base


@pytest.mark.parametrize("form", (ResetRoot, LazyResetRoot), indirect=True)
@pytest.mark.parametrize("field_name", ("number", "maybe"))
def test_reset_at_default_does_not_queue_a_flash(qapp, form, field_name):
    nested = form.nested_managers["child"]
    before = form.state.get_resolved_value(f"child.{field_name}")
    FlashTrace._records.clear()
    nested.reset_buttons[field_name].click()
    _flush(qapp)
    assert form.state.get_resolved_value(f"child.{field_name}") == before
    assert _queued_leaf_paths() == set()


@pytest.mark.parametrize("form", (ResetRoot, LazyResetRoot), indirect=True)
def test_group_reset_queues_only_changed_descendants(qapp, form):
    nested = form.nested_managers["child"]
    nested.update_parameter("number", 8)
    _flush(qapp)
    FlashTrace._records.clear()
    nested.reset_all_parameters()
    _flush(qapp)
    assert form.state.get_resolved_value("child.number") == 3
    assert form.state.get_resolved_value("child.maybe") is None
    assert _queued_leaf_paths() == {"child.number"}


@pytest.mark.parametrize("form", (LazyResetRoot,), indirect=True)
def test_explicit_default_reset_changes_provenance_without_value_flash(qapp, form):
    nested = form.nested_managers["child"]
    nested.update_parameter("number", 3)
    _flush(qapp)
    assert form.state.parameters["child.number"] == 3
    FlashTrace._records.clear()
    nested.reset_buttons["number"].click()
    _flush(qapp)
    assert form.state.parameters["child.number"] is None
    assert form.state.get_resolved_value("child.number") == 3
    assert _queued_leaf_paths() == set()


@pytest.mark.parametrize("form", (ResetRoot, LazyResetRoot), indirect=True)
@pytest.mark.parametrize("field_name", ("number", "maybe"))
def test_noop_reset_does_not_suppress_later_external_model_edit(qapp, form, field_name):
    nested = form.nested_managers["child"]
    nested.reset_buttons[field_name].click()
    _flush(qapp)
    FlashTrace._records.clear()
    form.state.update_parameter(f"child.{field_name}", 8)
    _flush(qapp)
    assert form.state.get_resolved_value(f"child.{field_name}") == 8
    assert nested.widgets[field_name].get_value() == 8
    assert _queued_leaf_paths() == {f"child.{field_name}"}
