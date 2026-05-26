"""Selection and item-activation workflow for manager widgets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar

from abc import ABC, abstractmethod
from metaclass_registry import AutoRegisterMeta

from pyqt_reactive.widgets.mixins import handle_selection_change_with_prevention


class SelectionPayloadProjection(ABC, metaclass=AutoRegisterMeta):
    """Projects the payload emitted by a manager selection signal."""

    __registry_key__ = "registry_key"
    __skip_if_no_key__ = True

    registry_key: ClassVar[str | None] = None

    @abstractmethod
    def selected(self, item: Any, item_id: str) -> Any:
        ...


@dataclass(frozen=True, slots=True)
class ItemSelectionPayloadProjection(SelectionPayloadProjection):
    """Emit the selected backing item."""

    registry_key = "item"

    def selected(self, item: Any, item_id: str) -> Any:
        del item_id
        return item


@dataclass(frozen=True, slots=True)
class ItemIdSelectionPayloadProjection(SelectionPayloadProjection):
    """Emit the selected backing item id."""

    registry_key = "item_id"

    def selected(self, item: Any, item_id: str) -> Any:
        del item
        return item_id


@dataclass(frozen=True)
class ManagerSelectionOperations:
    """Nominal operation port consumed by ManagerSelectionController."""

    list_widget: Any
    selected_items: Callable[[], list[Any]]
    item_from_list_item: Callable[[Any], Any]
    item_id: Callable[[Any], str]
    should_preserve_selection: Callable[[], bool]
    current_selection_id: Callable[[], str]
    set_selection_id: Callable[[str], None]
    selection_signal: Callable[[], Any]
    selected_payload: Callable[[Any, str], Any]
    cleared_payload: Any
    in_time_travel: Callable[[], bool]
    update_button_states: Callable[[], None]
    handle_item_double_click: Callable[[Any], None]


class ManagerSelectionController:
    """Owns selection mutation, selection signals, and item activation."""

    def selected_items(self, operations: ManagerSelectionOperations) -> list[Any]:
        selected_items = []
        for list_item in operations.list_widget.selectedItems():
            item = operations.item_from_list_item(list_item)
            if item is not None:
                selected_items.append(item)
        return selected_items

    def handle_selection_changed(self, operations: ManagerSelectionOperations) -> None:
        handle_selection_change_with_prevention(
            operations.list_widget,
            operations.selected_items,
            operations.item_id,
            operations.should_preserve_selection,
            operations.current_selection_id,
            lambda items: self._select_first(operations, items),
            lambda: self._clear_selection(operations),
        )
        operations.update_button_states()

    def handle_item_double_clicked(
        self,
        operations: ManagerSelectionOperations,
        list_item: Any,
    ) -> None:
        item = operations.item_from_list_item(list_item)
        if item is not None:
            operations.handle_item_double_click(item)

    def _select_first(
        self,
        operations: ManagerSelectionOperations,
        items: list[Any],
    ) -> None:
        item = items[0]
        item_id = operations.item_id(item)
        operations.set_selection_id(item_id)

        if not operations.in_time_travel():
            operations.selection_signal().emit(operations.selected_payload(item, item_id))

    def _clear_selection(self, operations: ManagerSelectionOperations) -> None:
        operations.set_selection_id("")

        if not operations.in_time_travel():
            operations.selection_signal().emit(operations.cleared_payload)
