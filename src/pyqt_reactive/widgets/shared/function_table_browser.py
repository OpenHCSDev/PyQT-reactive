"""
Function table browser widget using AbstractTableBrowser.

Displays function metadata in a searchable table with static columns.
Used as the table portion of FunctionSelectorDialog.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, ClassVar

from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.shared.abstract_table_browser import (
    AbstractTableBrowser, ColumnDef
)


class FunctionTableBrowser(AbstractTableBrowser[Dict[str, Any]]):
    """
    Table browser for function metadata.
    
    Static columns: Name, Module, Backend, Registry, Contract, Tags, Description
    Single-select mode.
    """
    
    # Column widths
    MODULE_WIDTH = 250
    DESCRIPTION_WIDTH = 300
    COLUMN_SPECS: ClassVar[tuple[tuple[str, str, int], ...]] = (
        ("Name", "name", 150),
        ("Module", "module", MODULE_WIDTH),
        ("Backend", "backend", 80),
        ("Registry", "registry", 80),
        ("Contract", "contract", 100),
        ("Tags", "tags", 100),
        ("Description", "doc", DESCRIPTION_WIDTH),
    )
    
    def __init__(self, color_scheme: Optional[ColorScheme] = None, parent=None):
        super().__init__(color_scheme=color_scheme, selection_mode='single', parent=parent)

    @staticmethod
    def _contract_display_name(contract: Any, *, unknown_label: str) -> str:
        if contract is None:
            return unknown_label
        if isinstance(contract, Enum):
            return contract.name
        return str(contract)
    
    def get_columns(self) -> List[ColumnDef]:
        """Static column definitions for function table."""
        return [
            ColumnDef(name=name, key=key, width=width)
            for name, key, width in self.COLUMN_SPECS
        ]
    
    def extract_row_data(self, item: Dict[str, Any]) -> List[str]:
        """Extract display values from function metadata dict."""
        # Get contract name
        contract = item.get('contract')
        contract_name = self._contract_display_name(contract, unknown_label="unknown")

        # Format tags
        tags = item.get('tags', [])
        tags_str = ", ".join(tags) if tags else ""

        # Truncate description
        doc = item.get('doc', '')
        description = doc[:150] + "..." if len(doc) > 150 else doc

        # Display original_name (just the function name) instead of name (which includes module prefix)
        # The module is shown separately in the Module column
        display_name = item.get('original_name', '') or item.get('name', 'unknown')

        return [
            display_name,
            item.get('module', 'unknown'),
            item.get('backend', 'unknown').title(),
            item.get('registry', 'unknown').title(),
            contract_name,
            tags_str,
            description,
        ]
    
    def get_searchable_text(self, item: Dict[str, Any]) -> str:
        """Return searchable text for function metadata."""
        contract = item.get('contract')
        contract_name = self._contract_display_name(contract, unknown_label="")

        tags = item.get('tags', [])

        # Include both original_name and name for searching
        original_name = item.get('original_name', '')
        name = item.get('name', '')

        return " ".join([
            original_name,
            name,
            item.get('module', ''),
            contract_name,
            " ".join(tags),
            item.get('doc', ''),
        ])
    
    def get_search_placeholder(self) -> str:
        return "Search functions by name, module, contract, or tags..."
