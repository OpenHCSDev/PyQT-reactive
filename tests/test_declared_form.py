"""The declared editor family and the form that composes it over an ObjectState."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated

from formbridge.forms.declared_fields import DeclaredField, Multiline
from objectstate import DottedFieldPath, ObjectState, set_base_config_type
from python_introspect import FieldLabel
from python_introspect.choices import LabelledChoices

from pyqt_reactive.forms.declared_editors import (
    QtBoolEditor,
    QtChoicesEditor,
    QtEnumEditor,
    QtIntEditor,
    QtMultilineEditor,
    QtOptionalEditor,
    QtStrEditor,
    QtValueEditor,
)
from pyqt_reactive.forms.declared_form import DeclaredForm, DeclaredGroup
from pyqt_reactive.theming import ColorScheme


class Size(Enum):
    SMALL = "small"
    LARGE = "large"


class Palette(LabelledChoices):
    def labelled_choices(self) -> tuple[tuple[str, str], ...]:
        return (("Red", "red"), ("Blue", "blue"))


@dataclass
class Margins:
    top: Annotated[int, FieldLabel("Top")] = 0


@dataclass
class Draft:
    title: Annotated[str, FieldLabel("Title"), "What the draft is called"] = ""
    count: Annotated[int, FieldLabel("Count")] = 1
    enabled: Annotated[bool, FieldLabel("Enabled")] = False
    colour: Annotated[str, FieldLabel("Colour"), Palette()] = "red"
    size: Annotated[Size, FieldLabel("Size")] = Size.SMALL
    note: Annotated[str, FieldLabel("Note"), Multiline()] = ""
    limit: Annotated[int | None, FieldLabel("Limit")] = None
    margins: Margins = field(default_factory=Margins)


def draft_state() -> ObjectState:
    set_base_config_type(Draft)
    return ObjectState(Draft())


def test_every_declared_field_gets_the_editor_its_kind_declares(qapp) -> None:
    state = draft_state()
    chosen = {name: type(QtValueEditor.declared_for(DeclaredField(state, DottedFieldPath(name))))
              for name in ("title", "count", "enabled", "colour", "size", "note", "limit")}

    assert chosen == {"title": QtStrEditor, "count": QtIntEditor, "enabled": QtBoolEditor,
                      "colour": QtChoicesEditor, "size": QtEnumEditor, "note": QtMultilineEditor,
                      "limit": QtOptionalEditor}


def test_form_edits_its_state_and_shows_a_refusal_under_the_field(qapp) -> None:
    state = draft_state()
    form = DeclaredForm(state, ColorScheme())
    form.show()
    count = form.editor(DottedFieldPath("count"))

    count.setText("7")
    form.finish()
    assert state.get_resolved_value("count") == 7
    assert not form.refused

    count.setText("seven")
    form.finish()
    assert state.get_resolved_value("count") == 7
    assert form.refused

    colour = form.editor(DottedFieldPath("colour"))
    assert [colour.itemText(index) for index in range(colour.count())] == ["Red", "Blue"]
    colour.activated.emit(1)
    assert state.get_resolved_value("colour") == "blue"
    form.leave_state()


def test_state_changes_repaint_the_editor_and_nested_fields_are_a_group(qapp) -> None:
    state = draft_state()
    form = DeclaredForm(state, ColorScheme())

    state.update_parameter("title", "renamed")
    assert form.editor(DottedFieldPath("title")).text() == "renamed"
    assert type(form.parts[-1]) is DeclaredGroup
    assert form.editor(DottedFieldPath("margins.top")).text() == "0"
    form.leave_state()
