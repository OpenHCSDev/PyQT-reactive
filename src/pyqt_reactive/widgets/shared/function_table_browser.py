"""
Function table browser widget using AbstractTableBrowser.

Displays function metadata in a searchable table with static columns.
Used as the table portion of FunctionSelectorDialog.
"""

from enum import Enum
from typing import ClassVar, List, Optional, Protocol, Sequence, cast

from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.shared.abstract_table_browser import (
    AbstractTableBrowser,
    ColumnDef,
    TableSelectionMode,
)


class FunctionTableRow(Protocol):
    """Structural contract for function metadata shown in the selector table."""

    name: str
    module: str
    contract: object
    tags: Sequence[str]
    doc: str
    display_name: str

    def get_memory_type(self) -> str: ...

    def get_registry_name(self) -> str: ...


def _function_tags(item: object) -> Sequence[str]:
    """Return the multivalued tag projection declared by the Tags column."""
    return cast(FunctionTableRow, item).tags


class FunctionTableBrowser(AbstractTableBrowser[FunctionTableRow]):
    """
    Table browser for function metadata.
    
    Static columns: Name, Module, Backend, Registry, Contract, Tags, Description
    Single-select mode.
    """
    
    # Column widths
    MODULE_WIDTH = 250
    DESCRIPTION_WIDTH = 300
    COLUMNS: ClassVar[tuple[ColumnDef, ...]] = (
        ColumnDef("Name", "name", 150),
        ColumnDef("Module", "module", MODULE_WIDTH),
        ColumnDef("Backend", "backend", 80, filterable=True),
        ColumnDef("Registry", "registry", 80, filterable=True),
        ColumnDef("Contract", "contract", 100, filterable=True),
        ColumnDef("Tags", "tags", 100, filterable=True, filter_values=_function_tags),
        ColumnDef("Description", "doc", DESCRIPTION_WIDTH),
    )

    def __init__(self, color_scheme: Optional[ColorScheme] = None, parent=None):
        super().__init__(
            color_scheme=color_scheme,
            selection_mode=TableSelectionMode.SINGLE,
            parent=parent,
        )

    @staticmethod
    def _contract_display_name(contract: object, *, unknown_label: str) -> str:
        if contract is None:
            return unknown_label
        if isinstance(contract, Enum):
            return contract.name
        return str(contract)
    
    def get_columns(self) -> List[ColumnDef]:
        """Static column definitions for function table."""
        return list(self.COLUMNS)
    
    def extract_row_data(self, item: FunctionTableRow) -> List[str]:
        """Extract display values from function metadata."""
        # Get contract name
        contract_name = self._contract_display_name(item.contract, unknown_label="unknown")

        # Format tags
        tags_str = ", ".join(item.tags) if item.tags else ""

        # Truncate description
        description = item.doc[:150] + "..." if len(item.doc) > 150 else item.doc

        return [
            item.display_name,
            item.module,
            item.get_memory_type().title(),
            item.get_registry_name().title(),
            contract_name,
            tags_str,
            description,
        ]
    
    def get_searchable_text(self, item: FunctionTableRow) -> str:
        """Return searchable text for function metadata."""
        contract_name = self._contract_display_name(item.contract, unknown_label="")

        return " ".join([
            item.display_name,
            item.name,
            item.module,
            contract_name,
            " ".join(item.tags),
            item.doc,
        ])
    
    def get_search_placeholder(self) -> str:
        return "Search functions by name, module, contract, or tags..."
