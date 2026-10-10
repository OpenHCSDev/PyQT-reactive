"""Fields whose admissible values are declared as AnnotationChoices metadata."""

from __future__ import annotations

from typing import Annotated

import pytest
from python_introspect import AnnotationChoices


class _Kind:
    pass


class _Alpha(_Kind):
    pass


class _Beta(_Kind):
    pass


class _KindChoices(AnnotationChoices):
    def choices(self) -> tuple[object, ...]:
        return (_Alpha, _Beta)

    def label(self, choice: object) -> str:
        return choice.__name__.strip("_").lower()


SCALAR = Annotated[type[_Kind] | None, _KindChoices()]
MULTIPLE = Annotated[list[type[_Kind]], _KindChoices()]


def test_scalar_choice_field_renders_declared_choices(qapp):
    from pyqt_reactive.forms.widget_strategies import create_pyqt6_widget

    widget = create_pyqt6_widget("kind", SCALAR, _Beta, "kind")

    assert tuple(widget.itemText(index) for index in range(widget.count())) == (
        "Default",
        "alpha",
        "beta",
    )
    assert widget.currentData() is _Beta


def test_multiple_choice_field_renders_checkbox_per_choice(qapp):
    from pyqt_reactive.forms.widget_strategies import create_pyqt6_widget

    widget = create_pyqt6_widget("kinds", MULTIPLE, [_Alpha], "kinds")

    assert [checkbox.text() for checkbox in widget.checkbox_widgets()] == [
        "alpha",
        "beta",
    ]
    assert widget.get_value() == [_Alpha]


def test_choice_values_convert_from_choices_and_labels() -> None:
    from pyqt_reactive.forms.parameter_form_service import ParameterFormService

    service = ParameterFormService()

    assert service.convert_value_to_type(_Alpha, SCALAR, "kind") is _Alpha
    assert service.convert_value_to_type("beta", SCALAR, "kind") is _Beta
    assert service.convert_value_to_type(["alpha", _Beta], MULTIPLE, "kinds") == [
        _Alpha,
        _Beta,
    ]
    with pytest.raises(ValueError):
        service.convert_value_to_type("gamma", SCALAR, "kind")
