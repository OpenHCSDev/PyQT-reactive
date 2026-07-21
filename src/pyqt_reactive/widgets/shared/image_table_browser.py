"""
Image table browser widget using AbstractTableBrowser.

Displays file metadata in a searchable table with dynamic columns.
Used as the table portion of ImageBrowserWidget.
"""

from collections.abc import Mapping
from typing import Callable, List, Optional

from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.shared.abstract_table_browser import (
    AbstractTableBrowser,
    ColumnDef,
    TableSelectionMode,
)

ImageTableValue = str | int | float | bool | None
ImageTableRow = Mapping[str, ImageTableValue]


class ImageTableBrowser(AbstractTableBrowser[ImageTableRow]):
    """
    Table browser for image/file metadata.
    
    Dynamic columns: Filename + metadata keys from file parser.
    Multi-select mode for batch streaming operations.
    """
    
    def __init__(
        self,
        color_scheme: Optional[ColorScheme] = None,
        metadata_value_formatter: Callable[[str, ImageTableValue], str] | None = None,
        parent=None,
    ):
        # Columns are dynamic - start with just Filename
        self._metadata_keys: List[str] = []
        self._metadata_value_formatter = metadata_value_formatter
        super().__init__(
            color_scheme=color_scheme,
            selection_mode=TableSelectionMode.MULTI,
            parent=parent,
        )
    
    def set_metadata_keys(self, metadata_keys: List[str]):
        """Set the metadata keys that define dynamic columns. Call before set_items()."""
        self._metadata_keys = metadata_keys
        self.reconfigure_columns()
    
    # Default widths for common metadata columns to keep table compact
    _COLUMN_WIDTHS = {
        'extension': 70,
        'channel': 70,
        'site': 50,
        'size': 80,
        'time': 100,
        'timestamp': 100,
    }

    def get_columns(self) -> List[ColumnDef]:
        """Dynamic column definitions based on metadata keys."""
        columns = [ColumnDef(name="Filename", key="filename", width=200)]

        for key in self._metadata_keys:
            width = self._COLUMN_WIDTHS.get(key.lower())
            columns.append(
                ColumnDef(
                    name=key.replace('_', ' ').title(),
                    key=key,
                    width=width,
                    filterable=True,
                )
            )

        return columns
    
    def extract_row_data(self, item: ImageTableRow) -> List[str]:
        """Extract display values from file metadata dict."""
        # First column is filename (stored as key, passed via item)
        row = [str(item["filename"])]

        # Remaining columns are metadata values
        for key in self._metadata_keys:
            value = item[key] if key in item else None
            row.append(self._format_value(key, value))

        return row

    def _format_value(self, key: str, value: ImageTableValue) -> str:
        """Format a metadata value for display."""
        if self._metadata_value_formatter is not None:
            return self._metadata_value_formatter(key, value)
        if value is None:
            return 'N/A'
        return str(value)

    def get_searchable_text(self, item: ImageTableRow) -> str:
        """Return searchable text for file metadata."""
        parts = [str(item["filename"])]

        for key in self._metadata_keys:
            if key not in item:
                continue
            value = item[key]
            if value is None:
                continue
            parts.append(str(value))

        return " ".join(parts)
    
    def get_search_placeholder(self) -> str:
        return "Search files..."
