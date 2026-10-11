"""Editable tables derive columns, editors and rows from a row dataclass."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Annotated

import pytest
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtWidgets import QCheckBox, QComboBox, QTableWidget, QTableWidgetItem
from python_introspect import FieldLabel

from pyqt_reactive.widgets.editable_table import (
    BooleanCellEditor,
    ChoiceCellEditor,
    DataclassFieldColumns,
    EditableTableController,
    EditableTableLayout,
    RecordTupleCellEditor,
    RowSuggestion,
    ScalarTextCellEditor,
    StructuredSelectorDialog,
)


class Subject(Enum):
    FILE = "file"
    DIRECTORY = "directory"


@dataclass(frozen=True)
class Clause:
    subject: Subject
    """What the clause matches."""
    value: str
    enabled: bool = True


@dataclass(frozen=True)
class Count:
    amount: int


@dataclass(frozen=True)
class Rule:
    name: Annotated[str, FieldLabel("Rule Name")]
    clauses: tuple[Clause, ...] = ()
    opaque: object = None


def test_columns_derive_from_fields_that_have_an_editor() -> None:
    columns = DataclassFieldColumns.of(Rule)

    assert [column.path for column in columns] == [("name",), ("clauses",)]
    assert columns.labels == ("Rule Name", "Clauses")
    assert not columns.is_isomorphic
    assert [type(column.editor) for column in DataclassFieldColumns.of(Clause)] == [
        ChoiceCellEditor,
        ScalarTextCellEditor,
        BooleanCellEditor,
    ]
    assert isinstance(columns.named("clauses").editor, RecordTupleCellEditor)
    assert DataclassFieldColumns.of(Clause).named("subject").tooltip == "What the clause matches."


def test_replacing_a_column_keeps_fields_without_a_column() -> None:
    marker = object()
    row = Rule(name="a", opaque=marker)

    edited = DataclassFieldColumns.of(Rule).named("name").replaced(row, "b")

    assert edited == Rule(name="b", opaque=marker)


def test_controller_round_trips_typed_rows(qapp) -> None:
    table = QTableWidget(0, 3)
    changes: list[int] = []
    controller = EditableTableController(
        table=table,
        columns=DataclassFieldColumns.of(Clause),
        apply_changes=lambda: changes.append(1),
    )
    rows = (Clause(Subject.FILE, "DNA"), Clause(Subject.DIRECTORY, "plate", enabled=False))

    controller.replace_all(rows)

    assert controller.rows() == rows
    assert isinstance(table.cellWidget(0, 0), QComboBox)
    assert isinstance(table.cellWidget(1, 2), QCheckBox)
    table.cellWidget(1, 2).setChecked(True)
    assert controller.rows()[1].enabled is True


def test_selector_dialog_edits_typed_rows_and_reports_incomplete_ones(qapp) -> None:
    existing = Clause(Subject.FILE, "DNA")
    dialog = StructuredSelectorDialog(
        element_type=Clause,
        suggestions=(RowSuggestion.of(Clause, subject=Subject.DIRECTORY, value="x"),),
        value=(existing,),
    )

    dialog._append_suggestion(dialog.suggestions.item(0).data(Qt.ItemDataRole.UserRole))
    assert dialog.value() == (existing, Clause(Subject.DIRECTORY, "x"))

    assert dialog.validation_label.text() == "All rows are structurally valid."

    count_dialog = StructuredSelectorDialog(element_type=Count, suggestions=(), value=())
    count_dialog.append_draft({})
    assert count_dialog.validation_label.text() == "Incomplete rows ignored: 1"
    assert count_dialog.value() == ()

    with pytest.raises(TypeError, match="fields without an editable column"):
        StructuredSelectorDialog(element_type=Rule, suggestions=(), value=())


def test_layout_keeps_final_row_visible_with_or_without_scrollbar(qapp) -> None:
    table = QTableWidget(2, 2)
    table.setItem(0, 0, QTableWidgetItem("field"))
    table.setItem(0, 1, QTableWidgetItem("short"))
    table.setItem(1, 0, QTableWidgetItem("imported metadata tables"))
    table.setItem(1, 1, QTableWidgetItem("a value wide enough to require scrolling"))
    EditableTableLayout.configure(table)
    EditableTableLayout.fit_to_rows(table)
    table.resize(180, table.height())
    table.show()
    try:
        for _ in range(4):
            qapp.processEvents()
        EditableTableLayout.fit_to_rows(table)
        qapp.processEvents()

        expected_rows_height = sum(table.rowHeight(row) for row in range(table.rowCount()))
        final_index = table.model().index(table.rowCount() - 1, 0)
        assert table.horizontalScrollBar().isVisible()
        assert table.viewport().height() >= expected_rows_height
        assert table.visualRect(final_index).bottom() <= table.viewport().rect().bottom()
        viewport_rect = QRect(
            table.viewport().mapTo(table, table.viewport().rect().topLeft()),
            table.viewport().size(),
        )
        bar = table.horizontalScrollBar()
        bar_rect = QRect(bar.mapTo(table, bar.rect().topLeft()), bar.size())
        assert not viewport_rect.intersects(bar_rect)

        table.resize(1200, table.height())
        for _ in range(4):
            qapp.processEvents()
        EditableTableLayout.fit_to_rows(table)
        qapp.processEvents()

        assert not table.horizontalScrollBar().isVisible()
        assert table.visualRect(final_index).bottom() <= table.viewport().rect().bottom()
    finally:
        table.close()
