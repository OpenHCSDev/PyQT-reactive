"""Editable Qt tables whose columns and cell editors derive from a row dataclass.

``DataclassFieldColumns.of(Row)`` gives one column per field a cell editor
accepts (nested dataclass fields contribute their own fields). Cell editors are
an ``AutoRegisterMeta`` family keyed by the annotation they edit; cells hold
typed values, never a text encoding of several fields. ``EditableTableController``
owns the Qt mechanics, the ObjectState semantic chrome and placeholder styling.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import MISSING, dataclass, field, fields, is_dataclass, replace
from enum import Enum
from functools import cache
from types import MappingProxyType, UnionType
from typing import (
    Annotated,
    Generic,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from metaclass_registry import AutoRegisterMeta
from objectstate import ObjectStateSubfieldSemanticIndex, StructuralValuePath
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from python_introspect import (
    AnnotationChoices,
    SignatureAnalyzer,
    declared_annotation_choices,
    declared_field_label,
)

from pyqt_reactive.forms.widget_strategies import PlaceholderConfig
from pyqt_reactive.widgets.no_scroll_spinbox import NoScrollComboBox
from pyqt_reactive.widgets.structural_table import (
    EditableTableSemanticBinding,
    StructuralTableCellTarget,
)

EditableRowT = TypeVar("EditableRowT")
INVALID_CELL_VALUE_ERRORS = (ValueError, TypeError, re.error)
"""Errors a row constructor raises for a value the user has not finished editing."""


@dataclass(frozen=True, slots=True)
class RowSuggestion:
    """Prefilled field values offered for a new record row in a picker dialog."""

    values: tuple[tuple[str, object], ...]
    label: str

    @classmethod
    def of(cls, row_type: type, **values: object) -> RowSuggestion:
        columns = DataclassFieldColumns.of(row_type)
        return cls(
            values=tuple(values.items()),
            label=":".join(
                columns.named(name).editor.display(value) for name, value in values.items()
            ),
        )


RowSuggestionMap = Mapping[type, tuple[RowSuggestion, ...]]


@dataclass(frozen=True, slots=True)
class CellEditContext:
    """What a cell editor needs from its table besides the cell value."""

    on_change: Callable[[], None]
    suggestions: RowSuggestionMap = field(default_factory=lambda: MappingProxyType({}))


def cell_editor_key(name: str, cls: type) -> str:
    return name


class CellEditor(ABC, metaclass=AutoRegisterMeta):
    """Cell editor family keyed by the field annotation it edits.

    A cell holds a *raw* value (the widget's own state, e.g. item text); the
    editor converts it to the field's typed value. No raw value is ever a
    serialized encoding of several fields.
    """

    __registry_key__ = "editor_key"
    __key_extractor__ = cell_editor_key
    __skip_if_no_key__ = True

    def __init__(self, annotation: object) -> None:
        self.annotation = annotation

    @classmethod
    def for_annotation(cls, annotation: object) -> CellEditor | None:
        for editor_type in cls.__registry__.values():
            if editor_type.accepts(annotation):
                return editor_type(annotation)
        return None

    @classmethod
    @abstractmethod
    def accepts(cls, annotation: object) -> bool: ...

    @abstractmethod
    def raw_for(self, value: object) -> object:
        """Return the raw cell state that renders ``value``."""

    @abstractmethod
    def empty_raw(self) -> object:
        """Raw state of a new cell whose field has no default."""

    @abstractmethod
    def value_from_raw(self, raw: object) -> object:
        """Return the typed field value; raise ``ValueError`` while incomplete."""

    @abstractmethod
    def display(self, value: object) -> str: ...

    @abstractmethod
    def create(
        self,
        table: QTableWidget,
        row: int,
        column: int,
        raw: object,
        context: CellEditContext,
    ) -> None: ...

    @abstractmethod
    def update(self, table: QTableWidget, row: int, column: int, raw: object) -> bool:
        """Update an existing cell in place; return False when it must be rebuilt."""

    @abstractmethod
    def raw(self, table: QTableWidget, row: int, column: int) -> object: ...

    @staticmethod
    def union_members(annotation: object) -> tuple[object, ...]:
        if get_origin(annotation) in (Union, UnionType):
            return get_args(annotation)
        return (annotation,)


class ScalarTextCellEditor(CellEditor):
    """Text item for ``str``/``int``/``float`` scalars, optionally ``None``."""

    SCALAR_TYPES = (str, int, float, bool)

    @classmethod
    def accepts(cls, annotation: object) -> bool:
        if annotation is bool:
            return False
        members = tuple(
            member for member in cls.union_members(annotation) if member is not type(None)
        )
        return bool(members) and all(member in cls.SCALAR_TYPES for member in members)

    @property
    def optional(self) -> bool:
        return type(None) in self.union_members(self.annotation)

    @property
    def scalar_type(self) -> type:
        members = tuple(
            member for member in self.union_members(self.annotation) if member is not type(None)
        )
        return members[0] if len(members) == 1 else str

    def raw_for(self, value: object) -> str:
        return "" if value is None else str(value)

    def empty_raw(self) -> str:
        return ""

    def value_from_raw(self, raw: object) -> object:
        text = str(raw).strip()
        if not text and self.optional:
            return None
        return self.scalar_type(text)

    def display(self, value: object) -> str:
        return self.raw_for(value)

    def create(self, table, row, column, raw, context) -> None:
        table.setItem(row, column, EditableTableItem(str(raw)))

    def update(self, table, row, column, raw) -> bool:
        item = table.item(row, column)
        if not isinstance(item, EditableTableItem):
            return False
        item.set_logical_text(str(raw))
        return True

    def raw(self, table, row, column) -> str:
        item = table.item(row, column)
        if item is None:
            return ""
        return EditableTableController._editable_item(item).data(
            EditableTableItem.LOGICAL_VALUE_ROLE
        )


class BooleanCellEditor(CellEditor):
    """Check box for ``bool`` fields."""

    @classmethod
    def accepts(cls, annotation: object) -> bool:
        return annotation is bool

    def raw_for(self, value: object) -> bool:
        return bool(value)

    def empty_raw(self) -> bool:
        return False

    def value_from_raw(self, raw: object) -> bool:
        return bool(raw)

    def display(self, value: object) -> str:
        return str(bool(value))

    def create(self, table, row, column, raw, context) -> None:
        checkbox = QCheckBox(table)
        checkbox.setChecked(bool(raw))
        checkbox.toggled.connect(lambda _checked: context.on_change())
        table.setCellWidget(row, column, checkbox)

    def update(self, table, row, column, raw) -> bool:
        checkbox = table.cellWidget(row, column)
        if not isinstance(checkbox, QCheckBox):
            return False
        blocked = checkbox.blockSignals(True)
        try:
            checkbox.setChecked(bool(raw))
        finally:
            checkbox.blockSignals(blocked)
        return True

    def raw(self, table, row, column) -> bool:
        checkbox = table.cellWidget(row, column)
        return isinstance(checkbox, QCheckBox) and checkbox.isChecked()


class ChoiceCellEditor(CellEditor):
    """Combo box whose choices are the field type's members.

    Declared ``AnnotationChoices`` supply their choices and labels; an ``Enum``
    type supplies its members; ``type[F]`` for an ``AutoRegisterMeta`` family
    supplies the family registry, labelled by each member's registry key.
    """

    COMBO_LOGICAL_TEXT_ROLE = Qt.ItemDataRole.UserRole + 1

    @classmethod
    def accepts(cls, annotation: object) -> bool:
        return (
            cls.declared_choices(annotation) is not None
            or cls.family(annotation) is not None
            or (isinstance(annotation, type) and issubclass(annotation, Enum))
        )

    @staticmethod
    def declared_choices(annotation: object) -> AnnotationChoices | None:
        if get_origin(annotation) is not Annotated:
            return None
        return declared_annotation_choices(annotation)

    @staticmethod
    def family(annotation: object) -> type | None:
        if get_origin(annotation) is not type:
            return None
        (member_type,) = get_args(annotation)
        return member_type if isinstance(member_type, AutoRegisterMeta) else None

    @property
    def choices(self) -> tuple[object, ...]:
        declared = self.declared_choices(self.annotation)
        if declared is not None:
            return declared.choices()
        family = self.family(self.annotation)
        if family is not None:
            return tuple(family.__registry__.values())
        return tuple(cast(type[Enum], self.annotation))

    def raw_for(self, value: object) -> object:
        return value

    def empty_raw(self) -> object:
        return self.choices[0]

    def value_from_raw(self, raw: object) -> object:
        return raw

    def display(self, value: object) -> str:
        declared = self.declared_choices(self.annotation)
        if declared is not None:
            return declared.label(value)
        family = self.family(self.annotation)
        if family is not None:
            return str(getattr(value, family.__registry_key__))
        return str(cast(Enum, value).value)

    def create(self, table, row, column, raw, context) -> None:
        combo = NoScrollComboBox(table)
        for choice in self.choices:
            text = self.display(choice)
            combo.addItem(text, choice)
            combo.setItemData(combo.count() - 1, text, self.COMBO_LOGICAL_TEXT_ROLE)
        combo.setCurrentIndex(self.index_of(combo, raw))
        combo.currentIndexChanged.connect(lambda _: context.on_change())
        combo.activated.connect(lambda _: context.on_change())
        table.setCellWidget(row, column, combo)

    def update(self, table, row, column, raw) -> bool:
        combo = table.cellWidget(row, column)
        if not isinstance(combo, QComboBox):
            return False
        index = self.index_of(combo, raw)
        if index < 0:
            return False
        blocked = combo.blockSignals(True)
        try:
            combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(blocked)
        return True

    def raw(self, table, row, column) -> object:
        combo = table.cellWidget(row, column)
        if not isinstance(combo, QComboBox):
            raise TypeError("Choice cells are rendered as combo boxes.")
        return combo.currentData()

    @staticmethod
    def index_of(combo: QComboBox, value: object) -> int:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                return index
        return -1


class RecordTupleCellEditor(CellEditor):
    """Picker cell for ``tuple[Record, ...]`` with columns derived from ``Record``."""

    @classmethod
    def accepts(cls, annotation: object) -> bool:
        if get_origin(annotation) is not tuple:
            return False
        arguments = get_args(annotation)
        return (
            len(arguments) == 2
            and arguments[1] is Ellipsis
            and isinstance(arguments[0], type)
            and is_dataclass(arguments[0])
        )

    @property
    def element_type(self) -> type:
        return get_args(self.annotation)[0]

    def raw_for(self, value: object) -> tuple[object, ...]:
        return tuple(cast(tuple, value))

    def empty_raw(self) -> tuple[object, ...]:
        return ()

    def value_from_raw(self, raw: object) -> tuple[object, ...]:
        return tuple(cast(tuple, raw))

    def display(self, value: object) -> str:
        columns = DataclassFieldColumns.of(self.element_type)
        return "; ".join(
            ":".join(
                text
                for column in columns.columns
                if (text := column.editor.display(column.value_of(element)))
            )
            for element in cast(tuple, value)
        )

    def create(self, table, row, column, raw, context) -> None:
        table.setCellWidget(
            row,
            column,
            StructuredSelectorCellWidget(
                editor=self,
                value=self.value_from_raw(raw),
                suggestions=context.suggestions.get(self.element_type, ()),
                apply_changes=context.on_change,
                parent=table,
            ),
        )

    def update(self, table, row, column, raw) -> bool:
        widget = table.cellWidget(row, column)
        if not isinstance(widget, StructuredSelectorCellWidget):
            return False
        widget.set_value_silently(self.value_from_raw(raw))
        return True

    def raw(self, table, row, column) -> tuple[object, ...]:
        widget = table.cellWidget(row, column)
        if not isinstance(widget, StructuredSelectorCellWidget):
            raise TypeError("Record-list cells are rendered as selector widgets.")
        return widget.value()


@dataclass(frozen=True, slots=True)
class DataclassFieldColumn:
    """One editable leaf field of a row dataclass, at ``path`` from the row."""

    index: int
    path: tuple[str, ...]
    declaring_type: type
    editor: CellEditor
    label: str
    tooltip: str | None
    default: object = MISSING

    @property
    def name(self) -> str:
        return self.path[-1]

    def value_of(self, row: object) -> object:
        value = row
        for name in self.path:
            value = getattr(value, name)
        return value

    def replaced(self, row: object, value: object) -> object:
        """Return ``row`` with this field replaced; every other field is kept."""

        return self._replaced(row, self.path, value)

    @classmethod
    def _replaced(cls, row: object, path: tuple[str, ...], value: object) -> object:
        name, *rest = path
        if rest:
            value = cls._replaced(getattr(row, name), tuple(rest), value)
        return replace(row, **{name: value})


@dataclass(frozen=True, slots=True)
class DataclassFieldColumns:
    """Columns derived from a row dataclass: one per field a cell editor accepts.

    Nested dataclass fields contribute their own fields. Fields no editor accepts
    have no column; editing a row through ``replaced`` keeps them unchanged.
    """

    row_type: type
    columns: tuple[DataclassFieldColumn, ...]

    @classmethod
    @cache
    def of(cls, row_type: type) -> DataclassFieldColumns:
        columns: list[DataclassFieldColumn] = []
        cls._collect(row_type, (), columns)
        return cls(row_type=row_type, columns=tuple(columns))

    @classmethod
    def _collect(
        cls,
        row_type: type,
        prefix: tuple[str, ...],
        columns: list[DataclassFieldColumn],
    ) -> None:
        hints = get_type_hints(row_type, include_extras=True)
        for row_field in fields(row_type):
            annotation, metadata = cls._split_annotated(hints[row_field.name])
            path = (*prefix, row_field.name)
            if isinstance(annotation, type) and is_dataclass(annotation):
                cls._collect(annotation, path, columns)
                continue
            editor = CellEditor.for_annotation(
                hints[row_field.name]
                if any(isinstance(item, AnnotationChoices) for item in metadata)
                else annotation
            )

            if editor is None:
                continue
            columns.append(
                DataclassFieldColumn(
                    index=len(columns),
                    path=path,
                    declaring_type=row_type,
                    editor=editor,
                    label=declared_field_label(hints[row_field.name])
                    or row_field.name.replace("_", " ").title(),
                    tooltip=SignatureAnalyzer.extract_field_documentation(
                        row_type,
                        row_field.name,
                    ),
                    default=row_field.default,
                )
            )

    @staticmethod
    def _split_annotated(annotation: object) -> tuple[object, tuple[object, ...]]:
        if get_origin(annotation) is Annotated:
            base, *metadata = get_args(annotation)
            return base, tuple(metadata)
        return annotation, ()

    def __len__(self) -> int:
        return len(self.columns)

    def __iter__(self):
        return iter(self.columns)

    def named(self, *path: str) -> DataclassFieldColumn:
        for column in self.columns:
            if column.path[-len(path) :] == path:
                return column
        raise KeyError(f"{self.row_type.__name__} has no column {'.'.join(path)}.")

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(column.label for column in self.columns)

    def apply_header_items(self, header_item: Callable[[int], QTableWidgetItem | None]):
        for column in self.columns:
            item = header_item(column.index)
            if item is not None and column.tooltip is not None:
                item.setToolTip(column.tooltip)

    @property
    def is_isomorphic(self) -> bool:
        return len(self.columns) == len(fields(self.row_type)) and all(
            len(column.path) == 1 for column in self.columns
        )

    def construct(self, values: tuple[object, ...]) -> object:
        """Build an isomorphic row from one typed value per field."""

        return self.row_type(**{column.name: value for column, value in zip(self.columns, values)})

    def draft_raw(self, values: Mapping[str, object]) -> tuple[object, ...]:
        """Raw cells for a new row: given values, then field defaults, then empty."""

        return tuple(
            column.editor.raw_for(values[column.name])
            if column.name in values
            else (
                column.editor.raw_for(column.default)
                if column.default is not MISSING
                else column.editor.empty_raw()
            )
            for column in self.columns
        )


class StructuredSelectorCellWidget(QWidget):
    """Read-only summary of a record list with a typed picker dialog."""

    def __init__(
        self,
        *,
        editor: RecordTupleCellEditor,
        value: tuple[object, ...],
        suggestions: tuple[RowSuggestion, ...],
        apply_changes: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.editor = editor
        self.suggestions = suggestions
        self._value = value
        self._apply_changes = apply_changes
        self.semantic_marker_label = QLabel("", self)
        self.semantic_marker_label.setVisible(False)
        self.line_edit = QLineEdit(editor.display(value), self)
        self.line_edit.setReadOnly(True)
        picker_button = QPushButton("...", self)
        picker_button.setFixedWidth(28)
        picker_button.clicked.connect(self._open_picker)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.semantic_marker_label)
        layout.addWidget(self.line_edit, 1)
        layout.addWidget(picker_button)

    def value(self) -> tuple[object, ...]:
        return self._value

    def set_value(self, value: tuple[object, ...]) -> None:
        self.set_value_silently(value)
        self._apply_changes()

    def set_value_silently(self, value: tuple[object, ...]) -> None:
        self._value = tuple(value)
        self.line_edit.setText(self.editor.display(self._value))

    def set_semantic_markers(self, markers: tuple[str, ...]) -> None:
        """Render ObjectState-owned markers without changing the edit value."""

        self.semantic_marker_label.setText("".join(markers))
        self.semantic_marker_label.setVisible(bool(markers))

    def create_dialog(self) -> StructuredSelectorDialog:
        return StructuredSelectorDialog(
            element_type=self.editor.element_type,
            suggestions=self.suggestions,
            value=self._value,
            parent=self,
        )

    def _open_picker(self) -> None:
        dialog = self.create_dialog()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.set_value(dialog.value())


class StructuredSelectorDialog(QDialog):
    """Typed editor for a record list; its columns derive from the record type."""

    def __init__(
        self,
        *,
        element_type: type,
        suggestions: tuple[RowSuggestion, ...],
        value: tuple[object, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        columns = DataclassFieldColumns.of(element_type)
        self.setWindowTitle(f"Edit {element_type.__name__} list")
        self.table = QTableWidget(0, len(columns), self)
        self.table.setHorizontalHeaderLabels(columns.labels)
        columns.apply_header_items(self.table.horizontalHeaderItem)
        self.validation_label = QLabel(self)
        self.controller: EditableTableController[object] = EditableTableController(
            table=self.table,
            columns=columns,
            apply_changes=self._update_validation_hint,
        )
        for element in value:
            self.controller.append(element)
        self.table.itemChanged.connect(lambda _item: self.controller.request_apply_changes())
        self.suggestions = QListWidget(self)
        for suggestion in suggestions:
            item = QListWidgetItem(suggestion.label)
            item.setData(Qt.ItemDataRole.UserRole, suggestion)
            self.suggestions.addItem(item)
        self.suggestions.itemDoubleClicked.connect(
            lambda item: self._append_suggestion(item.data(Qt.ItemDataRole.UserRole))
        )
        add_button = QPushButton("Add selected", self)
        add_button.clicked.connect(self._append_selected)
        add_row_button = QPushButton("Add row", self)
        add_row_button.clicked.connect(lambda: self.append_draft({}))
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addWidget(self.validation_label)
        layout.addWidget(add_row_button)
        layout.addWidget(QLabel("Suggestions", self))
        layout.addWidget(self.suggestions)
        layout.addWidget(add_button)
        layout.addWidget(buttons)
        self._update_validation_hint()

    def value(self) -> tuple[object, ...]:
        return self.controller.rows()

    def append_draft(self, values: Mapping[str, object]) -> None:
        self.controller.append_draft(values)
        self._update_validation_hint()

    def _append_selected(self) -> None:
        for item in self.suggestions.selectedItems():
            self._append_suggestion(item.data(Qt.ItemDataRole.UserRole))

    def _append_suggestion(self, suggestion: RowSuggestion) -> None:
        self.append_draft(dict(suggestion.values))

    def _update_validation_hint(self) -> None:
        invalid_rows = self.controller.incomplete_row_numbers()
        if invalid_rows:
            joined_rows = ", ".join(str(row) for row in invalid_rows)
            self.validation_label.setText(f"Incomplete rows ignored: {joined_rows}")
            return
        self.validation_label.setText("All rows are structurally valid.")


RawRow = tuple[object, ...]


@dataclass(slots=True, weakref_slot=True)
class EditableTableProgrammaticUpdateGuard:
    """Suppress table-driven change callbacks while the model updates the view."""

    depth: int = 0
    pending_release: bool = False
    programmatic_row_values: tuple[RawRow, ...] | None = None

    def __enter__(self) -> EditableTableProgrammaticUpdateGuard:
        self.depth += 1
        self.pending_release = False
        self.programmatic_row_values = None
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self.depth > 0:
            self.depth -= 1
        self.pending_release = True
        QTimer.singleShot(0, lambda: self._release_pending())

    @property
    def active(self) -> bool:
        return self.depth > 0

    def remember_rows(self, row_values: tuple[RawRow, ...]) -> None:
        """Record the table rows produced by the current programmatic update."""

        self.programmatic_row_values = row_values

    def suppress_pending_rows(
        self,
        row_values: tuple[RawRow, ...],
    ) -> None:
        """Suppress delayed callbacks that still reflect programmatic rows."""

        self.pending_release = True
        self.remember_rows(row_values)
        QTimer.singleShot(0, lambda: self._release_pending())

    def should_suppress_pending_rows(
        self,
        row_values: tuple[RawRow, ...],
    ) -> bool:
        """Whether a pending callback still reflects the programmatic rows."""

        return self.pending_release and self.programmatic_row_values == row_values

    def release(self) -> None:
        self.pending_release = False
        self.programmatic_row_values = None

    def _release_pending(self) -> None:
        if self.depth == 0:
            self.release()


class EditableTableItem(QTableWidgetItem):
    """QTableWidgetItem with separate logical/edit value and rendered chrome."""

    LOGICAL_VALUE_ROLE = Qt.ItemDataRole.UserRole
    RENDERED_TEXT_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self, value: str) -> None:
        super().__init__()
        self._logical_value = value
        self._rendered_text = value
        super().setData(Qt.ItemDataRole.DisplayRole, value)

    def data(self, role):
        if role == Qt.ItemDataRole.DisplayRole:
            return self._rendered_text
        if role == Qt.ItemDataRole.EditRole:
            return self._logical_value
        if role == self.LOGICAL_VALUE_ROLE:
            return self._logical_value
        if role == self.RENDERED_TEXT_ROLE:
            return self._rendered_text
        return super().data(role)

    def setData(self, role, value) -> None:  # noqa: N802 - Qt virtual method name
        text = "" if value is None else str(value)
        if role == Qt.ItemDataRole.EditRole:
            self.set_logical_text(text)
            return
        if role == Qt.ItemDataRole.DisplayRole:
            self.set_rendered_text(text)
            return
        if role == self.LOGICAL_VALUE_ROLE:
            self._logical_value = text
            super().setData(self.LOGICAL_VALUE_ROLE, text)
            return
        if role == self.RENDERED_TEXT_ROLE:
            self.set_rendered_text(text)
            return
        super().setData(role, value)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt virtual method name
        self.set_logical_text(text)

    def set_logical_text(self, value: str) -> None:
        self._logical_value = value
        self._rendered_text = value
        super().setData(self.LOGICAL_VALUE_ROLE, value)
        super().setData(self.RENDERED_TEXT_ROLE, value)
        super().setData(Qt.ItemDataRole.DisplayRole, value)

    def set_rendered_text(self, value: str) -> None:
        self._rendered_text = value
        super().setData(self.RENDERED_TEXT_ROLE, value)
        super().setData(Qt.ItemDataRole.DisplayRole, value)


@dataclass(frozen=True)
class EditableTableController(Generic[EditableRowT]):
    """Own editable Qt table mechanics for one isomorphic row dataclass.

    Every field of the row type has a column, so a row is constructed from its
    typed cell values without losing anything.
    """

    LOGICAL_VALUE_ROLE = EditableTableItem.LOGICAL_VALUE_ROLE
    RENDERED_TEXT_ROLE = EditableTableItem.RENDERED_TEXT_ROLE
    COMBO_LOGICAL_TEXT_ROLE = ChoiceCellEditor.COMBO_LOGICAL_TEXT_ROLE

    table: QTableWidget
    columns: DataclassFieldColumns
    apply_changes: Callable[[], None]
    suggestions: RowSuggestionMap = field(default_factory=lambda: MappingProxyType({}))
    semantic_binding: EditableTableSemanticBinding | None = None
    update_guard: EditableTableProgrammaticUpdateGuard = field(
        default_factory=EditableTableProgrammaticUpdateGuard,
    )

    def __post_init__(self) -> None:
        if not self.columns.is_isomorphic:
            raise TypeError(
                f"{self.columns.row_type.__name__} has fields without an editable "
                "column; edit it through replace-based typed rows instead."
            )

    @property
    def cell_context(self) -> CellEditContext:
        return CellEditContext(
            on_change=self.request_apply_changes,
            suggestions=self.suggestions,
        )

    def append(self, row_model: EditableRowT) -> None:
        self._append_raw(
            tuple(column.editor.raw_for(column.value_of(row_model)) for column in self.columns)
        )

    def append_draft(self, values: Mapping[str, object]) -> None:
        """Append a row prefilled with ``values`` that may not be complete yet."""

        self._append_raw(self.columns.draft_raw(values))

    def _append_raw(self, raw_row: RawRow) -> None:
        table_signals_blocked = self.table.blockSignals(True)
        try:
            row_index = self.table.rowCount()
            self.table.insertRow(row_index)
            for column, raw in zip(self.columns, raw_row, strict=True):
                self._set_cell(row_index, column, raw)
        finally:
            self.table.blockSignals(table_signals_blocked)

    def replace_all(self, row_models: tuple[EditableRowT, ...]) -> bool:
        """Replace table contents; return whether table structure changed."""

        with self.update_guard:
            table_signals_blocked = self.table.blockSignals(True)
            try:
                if self.table.rowCount() == len(row_models):
                    for row_index, row_model in enumerate(row_models):
                        for column in self.columns:
                            raw = column.editor.raw_for(column.value_of(row_model))
                            if not column.editor.update(self.table, row_index, column.index, raw):
                                self._set_cell(row_index, column, raw)
                    return False

                self.table.setRowCount(0)
                for row_model in row_models:
                    self.append(row_model)
                return True
            finally:
                self.table.blockSignals(table_signals_blocked)
                self.update_guard.remember_rows(self.row_values())

    def request_apply_changes(self) -> None:
        """Apply edits unless they are fallout from a programmatic table update."""

        if self.update_guard.active:
            return
        self._sync_item_logical_values_from_edit_role()
        if self.update_guard.pending_release:
            if self.update_guard.should_suppress_pending_rows(self.row_values()):
                return
            self.update_guard.release()
        self.apply_changes()

    def rows(self) -> tuple[EditableRowT, ...]:
        """Return the complete rows; incomplete rows are reported separately."""

        return tuple(
            row
            for row in (self._row_or_none(values) for values in self.row_values())
            if row is not None
        )

    def row_values(self) -> tuple[RawRow, ...]:
        """Return the current raw cell state for every row."""

        return tuple(
            tuple(column.editor.raw(self.table, row_index, column.index) for column in self.columns)
            for row_index in range(self.table.rowCount())
        )

    def incomplete_row_numbers(self) -> tuple[int, ...]:
        """One-based numbers of rows whose cells do not yet form a valid row."""

        return tuple(
            row_index + 1
            for row_index, values in enumerate(self.row_values())
            if self._row_or_none(values) is None
        )

    def has_incomplete_rows(self) -> bool:
        return bool(self.incomplete_row_numbers())

    def _row_or_none(self, raw_row: RawRow) -> EditableRowT | None:
        try:
            return cast(
                EditableRowT,
                self.columns.construct(
                    tuple(
                        column.editor.value_from_raw(raw)
                        for column, raw in zip(self.columns, raw_row, strict=True)
                    )
                ),
            )
        except INVALID_CELL_VALUE_ERRORS:
            return None

    def suppress_current_rows_until_idle(self) -> None:
        """Suppress delayed callbacks for the currently rendered row values."""

        self.update_guard.suppress_pending_rows(self.row_values())

    def _sync_item_logical_values_from_edit_role(self) -> None:
        """Update item backing values for a real table edit without re-emitting."""

        table_signals_blocked = self.table.blockSignals(True)
        try:
            for row_index in range(self.table.rowCount()):
                for column in self.columns:
                    if self.table.cellWidget(row_index, column.index) is not None:
                        continue
                    item = self.table.item(row_index, column.index)
                    if item is None:
                        continue
                    edit_value = item.data(Qt.ItemDataRole.EditRole)
                    if not isinstance(edit_value, str):
                        edit_value = item.text()
                    if item.data(self.LOGICAL_VALUE_ROLE) == edit_value:
                        continue
                    self._set_item_logical_text(item, edit_value)
        finally:
            self.table.blockSignals(table_signals_blocked)

    def remove_selected(self) -> bool:
        selected_rows = {index.row() for index in self.table.selectedIndexes()}
        if not selected_rows:
            return False
        table_signals_blocked = self.table.blockSignals(True)
        try:
            for row_index in sorted(selected_rows, reverse=True):
                self.table.removeRow(row_index)
        finally:
            self.table.blockSignals(table_signals_blocked)
        return True

    def _set_cell(
        self,
        row_index: int,
        column: DataclassFieldColumn,
        raw: object,
    ) -> None:
        column.editor.create(
            self.table,
            row_index,
            column.index,
            raw,
            self.cell_context,
        )
        self._apply_current_placeholder_text_style_to_cell(row_index, column)

    @classmethod
    def _set_item_logical_text(cls, item: EditableTableItem, value: str) -> None:
        cls._editable_item(item)
        item.set_logical_text(value)

    @staticmethod
    def _editable_item(item: QTableWidgetItem) -> EditableTableItem:
        if not isinstance(item, EditableTableItem):
            raise TypeError(
                "Editable table text cells must be EditableTableItem instances "
                f"for semantic chrome isolation, got {type(item).__name__}."
            )
        return item

    def _apply_current_placeholder_text_style_to_cell(
        self,
        row_index: int,
        column: DataclassFieldColumn,
    ) -> None:
        """Apply the table's current inherited-preview style to a newly built cell."""

        active = self.table.property("placeholder_text_style_active") is True
        widget = self.table.cellWidget(row_index, column.index)
        if widget is not None:
            self._apply_widget_placeholder_text_style(widget, active)
            return
        item = self.table.item(row_index, column.index)
        if item is not None:
            self._apply_item_placeholder_text_style(item, active)

    def apply_semantic_index(
        self,
        semantic_index: ObjectStateSubfieldSemanticIndex,
    ) -> None:
        """Apply ObjectState structural semantics to table cell chrome."""

        from objectstate.time_travel_profile import TimeTravelProfiler

        with TimeTravelProfiler.phase(
            "pyqt_reactive.editable_table.apply_semantic_index",
            rows=self.table.rowCount(),
            columns=self.table.columnCount(),
        ):
            with self.update_guard:
                table_signals_blocked = self.table.blockSignals(True)
                try:
                    for (
                        row_index,
                        column_index,
                    ), relative_path in self.semantic_paths().items():
                        semantic = semantic_index.leaf_for(relative_path)
                        if semantic is None:
                            continue
                        widget = self.table.cellWidget(row_index, column_index)
                        if widget is not None:
                            self._apply_widget_semantic(widget, semantic)
                            continue
                        item = self.table.item(row_index, column_index)
                        if item is not None:
                            self._apply_item_semantic(item, semantic)
                finally:
                    self.table.blockSignals(table_signals_blocked)
                    self.update_guard.remember_rows(self.row_values())

    def set_placeholder_text_style(self, active: bool) -> None:
        """Apply inherited-preview text styling to every rendered table cell."""

        with self.update_guard:
            self.apply_placeholder_text_style_to_table(self.table, active)
            self.update_guard.remember_rows(self.row_values())

    @classmethod
    def apply_placeholder_text_style_to_table(
        cls,
        table: QTableWidget,
        active: bool,
    ) -> None:
        """Apply or clear placeholder text styling without dimming table controls."""

        table_signals_blocked = table.blockSignals(True)
        try:
            table.setProperty("placeholder_text_style_active", active)
            for row_index in range(table.rowCount()):
                for column_index in range(table.columnCount()):
                    widget = table.cellWidget(row_index, column_index)
                    if widget is not None:
                        cls._apply_widget_placeholder_text_style(widget, active)
                        continue
                    item = table.item(row_index, column_index)
                    if item is not None:
                        cls._apply_item_placeholder_text_style(item, active)
        finally:
            table.blockSignals(table_signals_blocked)

    def semantic_paths(self) -> Mapping[tuple[int, int], StructuralValuePath]:
        """Return structural paths for all currently rendered cells."""

        if self.semantic_binding is None:
            return MappingProxyType({})
        return MappingProxyType(
            {
                (row_index, column.index): self.semantic_binding.relative_path_for_cell(
                    row_index,
                    column.index,
                )
                for row_index in range(self.table.rowCount())
                for column in self.columns
            }
        )

    def cell_target_for_semantic_path(
        self,
        relative_path: StructuralValuePath,
    ) -> StructuralTableCellTarget | None:
        """Return a concrete target for a structural cell path."""

        for (row_index, column_index), candidate in self.semantic_paths().items():
            if candidate != relative_path:
                continue
            return StructuralTableCellTarget(
                table=self.table,
                row_index=row_index,
                column_index=column_index,
                cell_widget=self.table.cellWidget(row_index, column_index),
            )
        return None

    @staticmethod
    def _semantic_tooltip(semantic) -> str:
        reasons: list[str] = [semantic.display_path]
        if semantic.dirty:
            reasons.append("* differs from saved value")
        if semantic.signature_diff:
            reasons.append("_ differs from signature default")
        if semantic.inherited_value:
            reasons.append("inherited resolved value")
        return "\n".join(reasons)

    @classmethod
    def _apply_item_semantic(cls, item: QTableWidgetItem, semantic) -> None:
        item = cls._editable_item(item)
        logical_value = item.data(cls.LOGICAL_VALUE_ROLE)
        if not isinstance(logical_value, str):
            edit_value = item.data(Qt.ItemDataRole.EditRole)
            logical_value = edit_value if isinstance(edit_value, str) else item.text()
            item.setData(cls.LOGICAL_VALUE_ROLE, logical_value)
        target_text = f"{''.join(semantic.semantic_markers)}{logical_value}"
        target_tooltip = cls._semantic_tooltip(semantic)
        font = item.font()
        if (
            item.text() == target_text
            and item.data(Qt.ItemDataRole.EditRole) == logical_value
            and item.data(cls.RENDERED_TEXT_ROLE) == target_text
            and font.underline() == semantic.signature_diff
            and item.toolTip() == target_tooltip
        ):
            return
        item.set_rendered_text(target_text)
        font.setUnderline(semantic.signature_diff)
        item.setFont(font)
        item.setToolTip(target_tooltip)

    @classmethod
    def _apply_widget_semantic(cls, widget: QWidget, semantic) -> None:
        target_tooltip = cls._semantic_tooltip(semantic)
        font = widget.font()
        if isinstance(widget, QComboBox):
            widget_marker_matches = cls._combo_current_marker_matches(
                widget,
                semantic.semantic_markers,
            )
        elif isinstance(widget, StructuredSelectorCellWidget):
            marker_text = "".join(semantic.semantic_markers)
            widget_marker_matches = (
                widget.semantic_marker_label.text() == marker_text
                and widget.semantic_marker_label.isVisible() == bool(marker_text)
            )
        else:
            widget_marker_matches = True
        if (
            widget.property("objectstate_dirty") == semantic.dirty
            and widget.property("objectstate_signature_diff") == semantic.signature_diff
            and widget.property("objectstate_inherited") == semantic.inherited_value
            and widget.toolTip() == target_tooltip
            and font.underline() == semantic.signature_diff
            and widget_marker_matches
        ):
            return
        if isinstance(widget, QComboBox):
            cls._apply_combo_semantic_markers(widget, semantic.semantic_markers)
        elif isinstance(widget, StructuredSelectorCellWidget):
            widget.set_semantic_markers(semantic.semantic_markers)
        widget.setProperty("objectstate_dirty", semantic.dirty)
        widget.setProperty("objectstate_signature_diff", semantic.signature_diff)
        widget.setProperty("objectstate_inherited", semantic.inherited_value)
        widget.setToolTip(target_tooltip)
        font.setUnderline(semantic.signature_diff)
        widget.setFont(font)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    @staticmethod
    def _combo_current_marker_matches(
        combo: QComboBox,
        markers: tuple[str, ...],
    ) -> bool:
        rendered_index = combo.currentIndex() if markers else -1
        return (
            combo.property("objectstate_rendered_markers") == markers
            and combo.property("objectstate_rendered_marker_index") == rendered_index
        )

    @classmethod
    def _apply_combo_semantic_markers(
        cls,
        combo: QComboBox,
        markers: tuple[str, ...],
    ) -> None:
        was_blocked = combo.blockSignals(True)
        try:
            cls._restore_combo_item_texts(combo)
            if markers and combo.currentIndex() >= 0:
                current_index = combo.currentIndex()
                combo.setItemText(
                    current_index,
                    f"{''.join(markers)}{cls._combo_logical_text(combo, current_index)}",
                )
                combo.setProperty("objectstate_rendered_marker_index", current_index)
            else:
                combo.setProperty("objectstate_rendered_marker_index", -1)
            combo.setProperty("objectstate_rendered_markers", markers)
        finally:
            combo.blockSignals(was_blocked)

    @classmethod
    def _restore_combo_item_texts(cls, combo: QComboBox) -> None:
        for index in range(combo.count()):
            combo.setItemText(index, cls._combo_logical_text(combo, index))

    @classmethod
    def _combo_logical_text(cls, combo: QComboBox, index: int) -> str:
        logical_text = combo.itemData(index, cls.COMBO_LOGICAL_TEXT_ROLE)
        if not isinstance(logical_text, str):
            raise TypeError("Editable table choice cells require logical text data.")
        return logical_text

    @classmethod
    def _apply_item_placeholder_text_style(
        cls,
        item: QTableWidgetItem,
        active: bool,
    ) -> None:
        font = item.font()
        font.setItalic(active)
        item.setFont(font)
        item.setForeground(
            QBrush(QColor(PlaceholderConfig.text_color_name())) if active else QBrush()
        )

    @classmethod
    def _apply_widget_placeholder_text_style(
        cls,
        widget: QWidget,
        active: bool,
    ) -> None:
        if isinstance(widget, StructuredSelectorCellWidget):
            cls._apply_line_edit_placeholder_text_style(widget.line_edit, active)
            return
        if isinstance(widget, QLineEdit):
            cls._apply_line_edit_placeholder_text_style(widget, active)
            return
        if isinstance(widget, QComboBox):
            widget.setStyleSheet(
                f"QComboBox {{ {PlaceholderConfig.text_style(include_opacity=False)} }}"
                if active
                else ""
            )

    @staticmethod
    def _apply_line_edit_placeholder_text_style(
        line_edit: QLineEdit,
        active: bool,
    ) -> None:
        line_edit.setStyleSheet(
            f"QLineEdit {{ {PlaceholderConfig.text_style(include_opacity=False)} }}"
            if active
            else ""
        )


class EditableTableLayout:
    """Shared layout policy for compact editable tables."""

    @staticmethod
    def configure(table: QTableWidget) -> None:
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        table.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(22)
        table.verticalHeader().setMinimumSectionSize(18)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

    @staticmethod
    def fit_to_rows(table: QTableWidget) -> None:
        table.ensurePolished()
        table.resizeRowsToContents()
        header = table.horizontalHeader()
        header_height = max(header.height(), header.sizeHint().height())
        row_height = sum(table.rowHeight(row) for row in range(table.rowCount()))
        if table.rowCount() == 0:
            row_height = table.verticalHeader().defaultSectionSize()
        scrollbar_height = table.horizontalScrollBar().sizeHint().height()
        frame = table.frameWidth() * 2
        viewport_vertical_margin = 2 * table.style().pixelMetric(
            QStyle.PixelMetric.PM_FocusFrameVMargin,
            None,
            table,
        )
        table.viewport().setMinimumHeight(row_height)
        table.setFixedHeight(
            header_height + row_height + scrollbar_height + frame + viewport_vertical_margin
        )
