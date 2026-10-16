"""A sectioned editor renders what its section declarations say."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import Annotated, ClassVar

import pytest
from formbridge.forms.raw_display_value import RawDisplayValue
from metaclass_registry import AutoRegisterMeta
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QComboBox, QPushButton, QTableWidget
from python_introspect import RegisteredClassChoices

from pyqt_reactive.forms.inline_dataclass_chrome import StandaloneChildChrome
from pyqt_reactive.widgets.editable_table import DataclassFieldColumns
from pyqt_reactive.widgets.sectioned_dataclass_editor import (
    EditorSection,
    NoTitleCheckbox,
    ReadOnlyTableSection,
    RenderedRowTable,
    SectionedDataclassEditor,
    TupleFieldSection,
    TupleSummarySection,
)
from pyqt_reactive.widgets.shared.abstract_table_browser import ColumnDef


class Shape(ABC, metaclass=AutoRegisterMeta):
    __registry_key__ = "name"
    __skip_if_no_key__ = True
    __registry__: ClassVar[dict[str, type[Shape]]] = {}
    name: ClassVar[str | None] = None


class Circle(Shape):
    name = "circle"


@dataclass(frozen=True)
class Mark:
    shape: Annotated[type[Shape], RegisteredClassChoices(Shape)]
    label: str = ""


@dataclass(frozen=True)
class Drawing:
    marks: tuple[Mark, ...] | None = None
    notes: tuple[Mark, ...] | None = None
    layers: tuple[str, ...] | None = None


@dataclass
class DrawingBase:
    pass


@dataclass(frozen=True)
class DrawingHolder:
    config: Drawing


@dataclass(frozen=True)
class DrawingRoot:
    outer: DrawingHolder


MARKS = TupleFieldSection(
    title="Marks",
    field_name="marks",
    row_type=Mark,
    new_row=lambda: Mark(Circle),
    add_label="Add mark",
    refreshes_alone=True,
)
NOTES = TupleFieldSection(
    title="Notes",
    field_name="notes",
    row_type=Mark,
    new_row=lambda: Mark(Circle, "note"),
    add_label="Add note",
)


class DrawingEditor(SectionedDataclassEditor):
    value_type = Drawing

    def sections(self) -> tuple[EditorSection, ...]:
        self.builds = getattr(self, "builds", 0) + 1
        layers = self.shown.display_field("layers") or ()
        return (
            ReadOnlyTableSection(
                title="Totals",
                columns=(ColumnDef("Marks", "marks", value=len),),
                rows=(self.shown.display_field("marks") or (),),
            ),
            TupleSummarySection(
                title="Layers",
                field_name="layers",
                columns=(ColumnDef("Layers", "layers", value=", ".join),),
                rows=(layers,) if layers else (),
                actions=(("Add layer", lambda: self.append_to_field("layers", "new")),),
            ),
            MARKS,
            NOTES,
        )


@pytest.fixture
def editor(qapp):
    widget = DrawingEditor.for_value(Drawing(marks=(Mark(Circle, "a"),)))
    yield widget
    widget.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def form_editor(qapp, owner):
    from objectstate import DottedFieldPath, ObjectState, ObjectStateRegistry, set_base_config_type
    from pyqt_reactive.forms.inline_dataclass_context import InlineDataclassFormContext
    from pyqt_reactive.forms.parameter_form_manager import FormManagerConfig, ParameterFormManager
    from pyqt_reactive.theming import ColorScheme

    value = Drawing(marks=(Mark(Circle, "a"),))
    source = {
        "": value,
        "config": DrawingHolder(value),
        "outer.config": DrawingRoot(DrawingHolder(value)),
    }[owner]
    set_base_config_type(DrawingBase)
    state = ObjectState(source, scope_id="sectioned-structural-target")
    ObjectStateRegistry.register(state, _skip_snapshot=True)
    path = DottedFieldPath(owner)
    scheme = ColorScheme()
    manager = ParameterFormManager(
        state=state,
        config=FormManagerConfig(
            field_id=path.parent.value,
            exclude_params=["config", "marks", "notes", "layers"],
            color_scheme=scheme,
        ),
    )
    context = InlineDataclassFormContext(
        state=state, manager=manager, owner_path=path,
        local_owner_path=DottedFieldPath(path.field_name), owner_type=Drawing,
        color_scheme=scheme, scope_accent_color=None,
    )
    widget = DrawingEditor(
        RawDisplayValue.shown_as_edited(Drawing, value), form_context=context,
    )
    try:
        yield widget
    finally:
        widget.deleteLater()
        manager.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        ObjectStateRegistry.clear()


@pytest.mark.parametrize(
    ("owner", "display_path", "child"),
    [
        ("config", "config.marks[0].label", "marks"),
        ("outer.config", "outer.config.marks[0].label", "marks"),
        ("", "marks[0].label", "marks"),
        ("config", "other.marks[0].label", None),
    ],
)
def test_structural_target_keeps_typed_owner_and_indexed_child(form_editor, owner, display_path, child):
    from objectstate import DottedFieldPath
    from pyqt_reactive.widgets.structural_table import (
        StructuralMaskedContainerTarget,
        StructuralTableCellTarget,
        resolve_inline_dataclass_structural_target,
    )

    result = resolve_inline_dataclass_structural_target(
        inline_widget=form_editor,
        inline_field_path=DottedFieldPath(owner),
        display_path=display_path,
    )
    if child is None:
        assert result is None
    else:
        assert result.child_field_name == child
        assert isinstance(result.target, StructuralMaskedContainerTarget)
        cell = result.target.masked_target
        assert isinstance(cell, StructuralTableCellTarget)
        assert cell.table is form_editor.table("marks")
        assert cell.row_index == 0
        assert cell.column_index == 1


def test_structural_target_exact_owner_and_root_are_distinct(editor):
    from objectstate import DottedFieldPath
    from pyqt_reactive.widgets.structural_table import (
        StructuralDescendantMaskTarget,
        resolve_inline_dataclass_structural_target,
    )

    result = resolve_inline_dataclass_structural_target(
        inline_widget=editor, inline_field_path=DottedFieldPath("config"), display_path="config",
    )
    assert result.child_field_name == "config"
    assert isinstance(result.target, StructuralDescendantMaskTarget)
    assert resolve_inline_dataclass_structural_target(
        inline_widget=editor, inline_field_path=DottedFieldPath(""), display_path="",
    ) is None


def test_sections_are_built_from_declarations(editor) -> None:
    assert isinstance(editor.chrome, StandaloneChildChrome)
    assert isinstance(editor.title_checkbox, NoTitleCheckbox)
    assert set(editor._rendered) == {"layers", "marks", "notes"}
    assert isinstance(editor.rendered("marks"), RenderedRowTable)
    assert editor.table("marks").rowCount() == 1
    assert editor.table("notes").rowCount() == 0
    assert {button.text() for button in editor.findChildren(QPushButton)} == {
        "Add layer",
        "Add mark",
        "Add note",
        "Remove selected",
    }


def test_row_edits_write_the_field_and_emit_once(editor) -> None:
    seen: list[object] = []
    editor.connect_change_signal(seen.append)

    editor.add_new_row("notes")
    editor.add_row("marks", Mark(Circle, "b"))

    assert editor.get_value().notes == (Mark(Circle, "note"),)
    assert editor.get_value().marks == (Mark(Circle, "a"), Mark(Circle, "b"))
    assert seen[-1] == editor.get_value()
    assert len(seen) == 2

    editor.table("marks").selectRow(0)
    editor.remove_selected_rows("marks")
    assert editor.get_value().marks == (Mark(Circle, "b"),)

    editor.disconnect_change_signal(seen.append)
    editor.add_new_row("notes")
    assert len(seen) == 3


def test_a_field_that_refreshes_alone_does_not_rebuild_other_sections(editor) -> None:
    builds = editor.builds
    notes_table = editor.table("notes")

    editor.set_value(Drawing(marks=(Mark(Circle, "a"), Mark(Circle, "c"))))

    assert editor.builds == builds
    assert editor.table("notes") is notes_table
    assert editor.table("marks").rowCount() == 2

    editor.set_value(Drawing(marks=(Mark(Circle, "a"), Mark(Circle, "c")), notes=(Mark(Circle),)))

    assert editor.builds == builds + 1
    assert editor.table("notes").rowCount() == 1


def test_inherited_rows_are_shown_and_styled_as_inherited(editor) -> None:
    inherited = Drawing(marks=(Mark(Circle, "from parent"),))

    editor.show_value(RawDisplayValue(Drawing, Drawing(), inherited))

    assert editor.get_value() == Drawing()
    assert editor.table("marks").rowCount() == 1
    assert editor.shown.shows_inherited("marks")
    assert editor.table("marks").property("placeholder_text_style_active") is True
    assert editor.table("notes").property("placeholder_text_style_active") is False

    editor.add_row("marks", Mark(Circle, "own"))

    assert editor.get_value().marks == (Mark(Circle, "from parent"), Mark(Circle, "own"))
    assert not editor.shown.shows_inherited("marks")


def test_summary_section_actions_edit_the_tuple_field(editor) -> None:
    editor.append_to_field("layers", "base")

    assert editor.get_value().layers == ("base",)
    assert editor.table("layers").item(0, 0).text() == "base"


def test_a_read_only_table_shows_each_row_through_its_columns(qapp) -> None:
    """Headers and cells come from one declaration, a dataclass field's included."""

    shape, label = (
        DataclassFieldColumns.of(Mark).named(name).read_only() for name in ("shape", "label")
    )
    length = ColumnDef("Length", "length", value=lambda mark: len(mark.label))
    table = QTableWidget(2, 3)

    EditorSection.fill(table, (shape, label, length), (Mark(Circle, "rim"), Mark(Circle)))

    assert [table.horizontalHeaderItem(index).text() for index in range(3)] == [
        shape.name,
        label.name,
        "Length",
    ]
    assert [table.item(0, index).text() for index in range(3)] == ["circle", "rim", "3"]
    assert [table.item(1, index).text() for index in range(3)] == ["circle", "", "0"]
    table.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_standalone_reset_writes_the_dataclass_default(editor) -> None:
    editor.chrome.reset_child("marks")

    assert editor.get_value().marks is None
    with pytest.raises(RuntimeError, match="require a form"):
        editor.child_field_identity("marks")


def test_a_member_registered_later_is_offered_with_no_editor_change(qapp) -> None:
    class Square(Shape):
        name = "square"

    try:
        widget = DrawingEditor.for_value(Drawing(marks=(Mark(Square),)))
        combo = widget.table("marks").cellWidget(
            0, DataclassFieldColumns.of(Mark).named("shape").index
        )
        assert isinstance(combo, QComboBox)
        assert {combo.itemText(index) for index in range(combo.count())} == {"circle", "square"}
        assert widget.get_value().marks[0].shape is Square
        widget.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    finally:
        del Shape.__registry__["square"]


def test_foreign_values_are_rejected(editor) -> None:
    with pytest.raises(TypeError, match="Expected Drawing"):
        editor.set_value(Mark(Circle))
