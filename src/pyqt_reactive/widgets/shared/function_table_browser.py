"""
Function table browser widget using AbstractTableBrowser.

Displays function metadata in a searchable table with static columns.
Used as the table portion of FunctionSelectorDialog.
"""

from collections.abc import Sequence
from typing import ClassVar, Protocol, cast

from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.shared.abstract_table_browser import (
    AbstractTableBrowser,
    ColumnDef,
    TableSelectionMode,
)


class FunctionTableRow(Protocol):
    """Structural contract for one projected function-catalog entry."""

    name: str
    module: str
    library: str
    backend_tags: Sequence[str]
    summary: str | None


def _function_tags(item: object) -> Sequence[str]:
    """Return the multivalued tag projection declared by the Tags column."""
    return cast(FunctionTableRow, item).backend_tags


class FunctionTableBrowser(AbstractTableBrowser[FunctionTableRow]):
    """
    Table browser for function metadata.

    Static columns: Name, Module, Library, Tags, Description
    Single-select mode.
    """

    # Column widths
    MODULE_WIDTH = 250
    DESCRIPTION_WIDTH = 300
    COLUMNS: ClassVar[tuple[ColumnDef, ...]] = (
        ColumnDef("Name", "name", 150),
        ColumnDef("Module", "module", MODULE_WIDTH),
        ColumnDef("Library", "library", 90, filterable=True),
        ColumnDef(
            "Tags",
            "backend_tags",
            120,
            filterable=True,
            filter_values=_function_tags,
        ),
        ColumnDef("Description", "summary", DESCRIPTION_WIDTH),
    )

    def __init__(self, color_scheme: ColorScheme | None = None, parent=None):
        super().__init__(
            color_scheme=color_scheme,
            selection_mode=TableSelectionMode.SINGLE,
            parent=parent,
        )

    def get_columns(self) -> list[ColumnDef]:
        """Static column definitions for function table."""
        return list(self.COLUMNS)

    def extract_row_data(self, item: FunctionTableRow) -> list[str]:
        """Extract display values from function metadata."""
        tags_str = ", ".join(item.backend_tags) if item.backend_tags else ""

        summary = item.summary or ""
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
        return " ".join([
            item.name,
            item.module,
            item.library,
            " ".join(item.backend_tags),
            item.summary or "",
        ])

    def get_search_placeholder(self) -> str:
        return "Search functions by name, module, library, or tags..."
