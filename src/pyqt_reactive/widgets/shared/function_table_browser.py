"""
Function table browser widget using AbstractTableBrowser.

Displays function metadata in a searchable table with static columns.
Used as the table portion of FunctionSelectorDialog.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from operator import attrgetter
from typing import ClassVar

from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.shared.abstract_table_browser import (
    AbstractTableBrowser,
    ColumnDef,
    TableSelectionMode,
)

FUNCTION_TABLE_COLUMN_METADATA_KEY = "function_table_column"


@dataclass(frozen=True, slots=True)
class FunctionTableColumnPresentation:
    """Presentation semantics owned by one function-row field."""

    title: str
    width: int
    filterable: bool = False
    multivalued: bool = False

    def column_def(self, field_name: str) -> ColumnDef:
        """Derive a generic table declaration for the owning field."""
        return ColumnDef(
            self.title,
            field_name,
            self.width,
            filterable=self.filterable,
            filter_values=(attrgetter(field_name) if self.multivalued else None),
        )


@dataclass(frozen=True, slots=True)
class FunctionTableRow:
    """Generic presentation row projected from a host function catalog."""

    name: str = field(
        metadata={
            FUNCTION_TABLE_COLUMN_METADATA_KEY: FunctionTableColumnPresentation(
                "Name",
                150,
            )
        }
    )
    module: str = field(
        metadata={
            FUNCTION_TABLE_COLUMN_METADATA_KEY: FunctionTableColumnPresentation(
                "Module",
                250,
            )
        }
    )
    library: str = field(
        metadata={
            FUNCTION_TABLE_COLUMN_METADATA_KEY: FunctionTableColumnPresentation(
                "Library",
                90,
                filterable=True,
            )
        }
    )
    backend_tags: tuple[str, ...] = field(
        metadata={
            FUNCTION_TABLE_COLUMN_METADATA_KEY: FunctionTableColumnPresentation(
                "Tags",
                120,
                filterable=True,
                multivalued=True,
            )
        }
    )
    summary: str | None = field(
        metadata={
            FUNCTION_TABLE_COLUMN_METADATA_KEY: FunctionTableColumnPresentation(
                "Description",
                300,
            )
        }
    )

    @classmethod
    def column_defs(cls) -> tuple[ColumnDef, ...]:
        """Derive columns from the row field declarations."""
        declarations = []
        for declared_field in fields(cls):
            presentation = declared_field.metadata[FUNCTION_TABLE_COLUMN_METADATA_KEY]
            if not isinstance(presentation, FunctionTableColumnPresentation):
                raise TypeError(f"{declared_field.name} has invalid function-table metadata")
            declarations.append(presentation.column_def(declared_field.name))
        return tuple(declarations)


def _require_function_table_row(item: FunctionTableRow) -> FunctionTableRow:
    """Reject domain objects that bypass the generic presentation projection."""
    if not isinstance(item, FunctionTableRow):
        raise TypeError("Function table items must be FunctionTableRow instances.")
    return item


def _require_function_table_rows(items: Mapping[str, FunctionTableRow]) -> None:
    """Validate a complete row projection before browser state changes."""
    for item in items.values():
        _require_function_table_row(item)


class FunctionTableBrowser(AbstractTableBrowser[FunctionTableRow]):
    """
    Table browser for function metadata.

    Static columns: Name, Module, Library, Tags, Description
    Single-select mode.
    """

    COLUMNS: ClassVar[tuple[ColumnDef, ...]] = FunctionTableRow.column_defs()

    def __init__(self, color_scheme: ColorScheme | None = None, parent=None):
        super().__init__(
            color_scheme=color_scheme,
            selection_mode=TableSelectionMode.SINGLE,
            parent=parent,
        )

    def set_items(self, items: dict[str, FunctionTableRow]) -> None:
        """Replace the authoritative row projection after nominal validation."""
        _require_function_table_rows(items)
        super().set_items(items)

    def set_filtered_items(self, filtered_items: dict[str, FunctionTableRow]) -> None:
        """Replace the external filtered projection after nominal validation."""
        _require_function_table_rows(filtered_items)
        super().set_filtered_items(filtered_items)

    def get_columns(self) -> list[ColumnDef]:
        """Static column definitions for function table."""
        return list(self.COLUMNS)

    def extract_row_data(self, item: FunctionTableRow) -> list[str]:
        """Extract display values from function metadata."""
        item = _require_function_table_row(item)
        tags_str = ", ".join(item.backend_tags)

        summary = item.summary
        if summary is None:
            summary = ""
        description = summary[:150] + "..." if len(summary) > 150 else summary

        return [
            item.name,
            item.module,
            item.library,
            tags_str,
            description,
        ]

    def get_searchable_text(self, item: FunctionTableRow) -> str:
        """Return searchable text for function metadata."""
        item = _require_function_table_row(item)
        return " ".join(
            [
                item.name,
                item.module,
                item.library,
                " ".join(item.backend_tags),
                item.summary or "",
            ]
        )

    def get_search_placeholder(self) -> str:
        return "Search functions by name, module, library, or tags..."
