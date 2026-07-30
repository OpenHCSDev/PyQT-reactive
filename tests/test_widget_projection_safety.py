"""Regression tests for typed writable form projections."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import pytest


def test_mapping_edit_round_trip_preserves_object_state_type(qapp):
    """A mapping edit reaches ObjectState as a mapping, never as display text."""
    from objectstate import (
        ObjectState,
        ObjectStateRegistry,
        set_base_config_type,
    )

    from pyqt_reactive.forms.parameter_form_manager import (
        FormManagerConfig,
        ParameterFormManager,
    )
    from pyqt_reactive.forms.widget_strategies import TypedLiteralContainerEdit
    from pyqt_reactive.theming import ColorScheme

    @dataclass
    class BaseConfig:
        output_dir: str = "/tmp"

    @dataclass
    class MappingConfig:
        chart_colors: dict[str, str] = field(
            default_factory=lambda: {"cpu": "#ffffff"}
        )

    set_base_config_type(BaseConfig)
    ObjectStateRegistry.clear()
    state = ObjectState(MappingConfig(), scope_id="test::typed_mapping_projection")
    manager = ParameterFormManager(
        state=state,
        config=FormManagerConfig(
            color_scheme=ColorScheme(),
            use_scroll_area=False,
        ),
    )

    try:
        qapp.processEvents()
        widget = manager.widgets["chart_colors"]
        assert isinstance(widget, TypedLiteralContainerEdit)
        assert widget.get_value() == {"cpu": "#ffffff"}

        widget.setText("{'cpu': '#ff0000', 'memory': '#00ff00'}")
        next(iter(widget._text_change_emitters.values())).flush()

        rebuilt = state.to_object()
        assert rebuilt.chart_colors == {
            "cpu": "#ff0000",
            "memory": "#00ff00",
        }
        assert isinstance(rebuilt.chart_colors, dict)

        widget.setText("{'cpu': 4}")
        with pytest.raises(ValueError, match="expected str, got int"):
            manager.validate_current_values()
        assert state.to_object().chart_colors == {
            "cpu": "#ff0000",
            "memory": "#00ff00",
        }
        widget.setText("{'cpu': '#ff0000', 'memory': '#00ff00'}")
        next(iter(widget._text_change_emitters.values())).flush()
    finally:
        manager.deleteLater()
        ObjectStateRegistry.clear()


@pytest.mark.parametrize(
    ("annotation", "initial_value", "edited_text", "expected"),
    (
        (list[str], ["a"], "['a', 'b']", ["a", "b"]),
        (tuple[int, ...], (1,), "(1, 2)", (1, 2)),
        (dict[str, int], {"a": 1}, "{'a': 2}", {"a": 2}),
    ),
)
def test_literal_container_editor_preserves_declared_container_kind(
    qapp,
    annotation,
    initial_value,
    edited_text,
    expected,
):
    """Literal-container dispatch is explicit and returns real containers."""
    from pyqt_reactive.forms.widget_strategies import (
        TypedLiteralContainerEdit,
        create_pyqt6_widget,
    )

    widget = create_pyqt6_widget(
        "value",
        annotation,
        initial_value,
        "value",
    )
    assert isinstance(widget, TypedLiteralContainerEdit)
    assert widget.get_value() == initial_value

    widget.setText(edited_text)

    assert widget.get_value() == expected
    assert type(widget.get_value()) is type(initial_value)


def test_literal_container_editor_rejects_invalid_or_wrong_kind(qapp):
    """Invalid text cannot cross the writable widget boundary."""
    from pyqt_reactive.forms.widget_strategies import create_pyqt6_widget

    widget = create_pyqt6_widget(
        "chart_colors",
        dict[str, str],
        {"cpu": "#ffffff"},
        "chart_colors",
    )

    widget.setText("{")
    assert not widget.hasAcceptableInput()
    with pytest.raises(ValueError, match="valid dict literal"):
        widget.get_value()

    widget.setText("['cpu', '#ffffff']")
    assert not widget.hasAcceptableInput()
    with pytest.raises(ValueError, match="Expected dict, got list"):
        widget.get_value()

    assert "Python dict literal" in widget.toolTip()
    assert "{'key': 'value'}" in widget.toolTip()


def test_literal_union_editor_round_trips_each_declared_member(qapp):
    """Heterogeneous literal-safe unions retain the selected runtime member."""
    from pyqt_reactive.forms.widget_strategies import (
        TypedLiteralUnionEdit,
        create_pyqt6_widget,
    )

    annotation = list[str] | str | int | None
    widget = create_pyqt6_widget(
        "well_filter",
        annotation,
        None,
        "well_filter",
    )

    assert isinstance(widget, TypedLiteralUnionEdit)
    assert widget.get_value() is None
    assert "Plain unquoted text is accepted as str" in widget.toolTip()

    widget.setText("['A01', 'B01']")
    assert widget.get_value() == ["A01", "B01"]

    widget.setText("7")
    assert widget.get_value() == 7
    assert type(widget.get_value()) is int

    widget.setText("A01")
    assert widget.get_value() == "A01"

    widget.setText("(1, 2)")
    assert not widget.hasAcceptableInput()
    with pytest.raises(ValueError, match="expected .*got tuple"):
        widget.get_value()


def test_incomplete_union_literal_is_not_emitted_as_plain_string(qapp):
    """Structural literal intent remains invalid until the literal is complete."""
    from pyqt_reactive.forms.widget_strategies import create_pyqt6_widget

    widget = create_pyqt6_widget(
        "well_filter",
        list[str] | str | int | None,
        None,
        "well_filter",
    )
    emitted = []
    callback = emitted.append
    widget.connect_change_signal(callback)

    widget.setText("[")
    widget._text_change_emitters[callback].flush()

    assert not widget.hasAcceptableInput()
    assert emitted == []
    with pytest.raises(ValueError, match="Expected a valid literal"):
        widget.get_value()


def test_non_optional_literal_union_rejects_empty_value(qapp):
    """An empty editor cannot manufacture None outside the declared union."""
    from pyqt_reactive.forms.widget_strategies import create_pyqt6_widget

    widget = create_pyqt6_widget(
        "value",
        list[str] | int,
        3,
        "value",
    )

    widget.clear()

    assert not widget.hasAcceptableInput()
    with pytest.raises(ValueError, match="is required"):
        widget.get_value()


def test_invalid_literal_is_not_emitted(qapp):
    """Transient invalid text leaves the last semantic mapping untouched."""
    from pyqt_reactive.forms.widget_strategies import create_pyqt6_widget

    widget = create_pyqt6_widget(
        "chart_colors",
        dict[str, str],
        {"cpu": "#ffffff"},
        "chart_colors",
    )
    emitted = []
    callback = emitted.append
    widget.connect_change_signal(callback)

    widget.setText("{")
    widget._text_change_emitters[callback].flush()

    assert emitted == []


def test_form_validation_service_surfaces_invalid_literal(qapp):
    """Callers receive one semantic validation failure without Qt type checks."""
    from types import SimpleNamespace

    from pyqt_reactive.forms.form_value_validation import (
        FORM_VALUE_VALIDATION,
        FormValueValidationError,
    )
    from pyqt_reactive.forms.widget_strategies import create_pyqt6_widget

    widget = create_pyqt6_widget(
        "chart_colors",
        dict[str, str],
        {"cpu": "#ffffff"},
        "chart_colors",
    )
    widget.setText("{")
    manager = SimpleNamespace(
        field_id="performance_monitor",
        widgets={"chart_colors": widget},
        nested_managers={},
    )

    with pytest.raises(
        FormValueValidationError,
        match=r"performance_monitor\.chart_colors.*valid dict literal",
    ):
        FORM_VALUE_VALIDATION.validate_current_values(manager)


def test_recursive_mapping_items_reach_object_state_as_declared_types(qapp):
    """Literal parsing and the semantic converter preserve nested item identity."""
    from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type

    from pyqt_reactive.forms.parameter_form_service import ParameterFormService
    from pyqt_reactive.forms.widget_strategies import create_pyqt6_widget

    class Mode(Enum):
        FAST = "fast"
        SAFE = "safe"

    @dataclass
    class BaseConfig:
        output_dir: str = "/tmp"

    @dataclass
    class MappingConfig:
        modes: dict[str, Mode] = field(
            default_factory=lambda: {"cpu": Mode.SAFE}
        )

    set_base_config_type(BaseConfig)
    ObjectStateRegistry.clear()
    state = ObjectState(
        MappingConfig(),
        scope_id="test::recursive_mapping_projection",
    )
    widget = create_pyqt6_widget(
        "modes",
        dict[str, Mode],
        {"cpu": Mode.SAFE},
        "modes",
    )

    try:
        widget.setText("{'cpu': 'fast', 'gpu': 'safe'}")
        converted = ParameterFormService().convert_value_to_type(
            widget.get_value(),
            dict[str, Mode],
            "modes",
            MappingConfig,
        )
        state.update_parameter("modes", converted)

        rebuilt = state.to_object()
        assert rebuilt.modes == {
            "cpu": Mode.FAST,
            "gpu": Mode.SAFE,
        }
        assert all(isinstance(value, Mode) for value in rebuilt.modes.values())
    finally:
        ObjectStateRegistry.clear()


def test_enum_and_path_keep_their_authoritative_typed_projections(qapp):
    """The safety boundary does not divert enum or path annotations to text."""
    from PyQt6.QtWidgets import QComboBox

    from pyqt_reactive.forms.widget_strategies import (
        convert_widget_value_to_type,
        create_pyqt6_widget,
    )
    from pyqt_reactive.widgets.enhanced_path_widget import EnhancedPathWidget

    class Mode(Enum):
        A = "a"
        B = "b"

    enum_widget = create_pyqt6_widget("mode", Mode, Mode.B, "mode")
    path_widget = create_pyqt6_widget(
        "output_path",
        Path,
        Path("/tmp/output"),
        "output_path",
    )

    assert isinstance(enum_widget, QComboBox)
    assert enum_widget.currentData() is Mode.B
    assert isinstance(path_widget, EnhancedPathWidget)
    assert convert_widget_value_to_type(path_widget.get_value(), Path) == Path(
        "/tmp/output"
    )


def test_unsupported_annotations_fail_loud_without_string_fallback(
    qapp,
    monkeypatch,
):
    """Magicgui failure cannot silently manufacture a writable string field."""
    import pyqt_reactive.forms.widget_strategies as widget_strategies

    def fail_creation(**_kwargs):
        raise RuntimeError("unsupported")

    monkeypatch.setattr(widget_strategies, "create_widget", fail_creation)

    with pytest.raises(
        widget_strategies.UnsupportedWidgetTypeError,
        match="parameter 'opaque'.*annotation 'Any'",
    ):
        widget_strategies.create_pyqt6_widget(
            "opaque",
            Any,
            object(),
            "opaque",
        )


def test_no_parallel_widget_factory_or_string_fallback_authority():
    """Static gate: type dispatch has one owner and cannot regain text fallback."""
    package_root = Path(__file__).parents[1] / "src" / "pyqt_reactive" / "forms"
    strategies_path = package_root / "widget_strategies.py"

    assert not (package_root / "widget_factory.py").exists()

    source = strategies_path.read_text()
    tree = ast.parse(source)
    forbidden_symbols = {
        "create_string_fallback_widget",
        "register_openhcs_widgets",
        "_register_path_widget_strategy",
        "_register_none_aware_lineedit_strategy",
        "WIDGET_TYPE_REGISTRY",
        "WidgetFactory",
    }
    declared_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert forbidden_symbols.isdisjoint(declared_names)

    magicgui_factory = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "MagicGuiWidgetFactory"
    )
    fallback_calls = [
        node
        for node in ast.walk(magicgui_factory)
        if isinstance(node, ast.Attribute)
        and node.attr == "create_string"
    ]
    assert fallback_calls == []


def test_union_and_nested_field_semantics_have_no_parallel_fallbacks():
    """Static gate: union and field identity remain derived from declarations."""
    forms_root = Path(__file__).parents[1] / "src" / "pyqt_reactive" / "forms"
    parameter_info_source = (forms_root / "parameter_info_types.py").read_text()
    parameter_type_source = (forms_root / "parameter_type_utils.py").read_text()
    service_source = (forms_root / "parameter_form_service.py").read_text()

    assert "get_origin(param_type) is Union" not in parameter_info_source
    assert "get_origin(param_type) is Union" not in parameter_type_source
    assert "get_obj_type_for_param" not in parameter_type_source
    assert "resolve_union_type" not in parameter_type_source
    assert "get_field_path_with_fail_loud" not in service_source
    assert "__name__.lower().replace('config', '')" not in service_source
    assert "Handle Union types" not in service_source
