"""Qt list-widget surface implementing formbridge's ManagerListSurface."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from formbridge.managers.selection_controller import ManagerListSurface
from PySide6.QtCore import QItemSelectionModel, QSignalBlocker


class QtManagerListSurface(ManagerListSurface):
    """Polymorphic Qt backend for formbridge's ManagerSelectionController."""

    def __init__(self, list_widget: Any, selection_signal: Callable[[], Any]) -> None:
        self._list_widget = list_widget
        self._selection_signal = selection_signal

    def row_count(self) -> int:
        return self._list_widget.count()

    def row_item_at(self, index: int) -> Any:
        return self._list_widget.item(index)

    def row_item_data(self, row_item: Any) -> Any:
        return row_item

    def selected_row_items(self) -> Sequence[Any]:
        return self._list_widget.selectedItems()

    def select_row_item(self, row_item: Any) -> None:
        self._list_widget.setCurrentItem(
            row_item, QItemSelectionModel.SelectionFlag.ClearAndSelect
        )

    def restore_row_item(self, row_item: Any) -> None:
        with QSignalBlocker(self._list_widget):
            self._list_widget.setCurrentItem(
                row_item, QItemSelectionModel.SelectionFlag.ClearAndSelect
            )

    def scroll_to_row_item(self, row_item: Any) -> None:
        self._list_widget.scrollToItem(row_item)

    def emit_selection(self, payload: Any) -> None:
        self._selection_signal().emit(payload)
