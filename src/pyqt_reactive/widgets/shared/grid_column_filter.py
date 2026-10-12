"""Keeps a grid selector and one table column's filter showing the same selection."""

from __future__ import annotations

from collections.abc import Mapping

from PyQt6.QtCore import QObject

from pyqt_reactive.widgets.grid_selector import GridPosition, GridSelectorWidget
from pyqt_reactive.widgets.shared.record_table_browser import RecordTableBrowser


class GridColumnFilterLink(QObject):
    """The column filter owns the selection; the grid is a second way to edit it.

    Selecting cells sets the column filter to those values, and no selected
    cell means no filter. A filter change selects the filtered values' cells;
    an inactive filter (every value admitted) shows as no selected cell.
    """

    def __init__(
        self,
        grid: GridSelectorWidget,
        table: RecordTableBrowser,
        column_key: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.grid = grid
        self.table = table
        self.column_key = column_key
        grid.cells_selected.connect(self._filter_to_cells)
        table.column_filter_selection_changed.connect(self._select_filtered_cells)

    def _filter_to_cells(self, cell_ids: set[str]) -> None:
        self.table.set_column_filter_selection(
            self.column_key,
            self.table.value_labels.texts(self.column_key, sorted(cell_ids)) if cell_ids else None,
        )

    def _select_filtered_cells(self, column_key: str, selected_texts: frozenset[str]) -> None:
        if column_key != self.column_key:
            return
        cells = (
            {value.raw for value in self.table.value_labels.shown(column_key, selected_texts)}
            if self.table.is_column_filter_active(column_key)
            else set()
        )
        self.grid.select_cells(cells, emit_signal=False)

    def column_values(self) -> set[str]:
        """The column's raw values over every loaded row."""
        return {
            str(item[self.column_key])
            for item in self.table.all_items.values()
            if item.get(self.column_key) is not None
        }

    def offer_cells(self, cell_at_position: Mapping[GridPosition, str] | None = None) -> None:
        """Offer the column's values as cells.

        Positions come from the grid's addressing unless the owner knows them
        (a source that spells rows and columns its own way).
        """
        dimensions = (
            (
                max(row for row, _column in cell_at_position),
                max(column for _row, column in cell_at_position),
            )
            if cell_at_position
            else None
        )
        self.grid.set_available_cells(self.column_values(), dimensions, cell_at_position)
