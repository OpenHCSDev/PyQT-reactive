"""List update pipeline for AbstractManagerWidget."""

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem

from pyqt_reactive.widgets.mixins import preserve_selection_during_update

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ManagerListUpdateOperations:
    """Nominal operation port consumed by ManagerListUpdater."""

    item_list: Any
    backing_items: list[Any]
    item_id: Callable[[Any], str]
    should_preserve_selection: Callable[[], bool]
    placeholder: Callable[[], Optional[tuple[str, Any]]]
    prepare_update: Callable[[], Any]
    clear_scope_cache: Callable[[], None]
    subscribed_scope_ids: Callable[[], set[str]]
    scope_for_item: Callable[[Any], str]
    cleanup_flash_subscriptions: Callable[[], None]
    clear_scope_to_list_item: Callable[[], None]
    format_item: Callable[[Any, int, Any], Any]
    list_item_data_for: Callable[[Any, int], Any]
    tooltip_for: Callable[[Any], str]
    extra_data_for: Callable[[Any, int], dict[int, Any]]
    set_styling_roles: Callable[[QListWidgetItem, Any, Any], None]
    apply_scope_color: Callable[[QListWidgetItem, Any, int], None]
    subscribe_flash: Callable[[Any, QListWidgetItem, str], None]
    post_update: Callable[[], None]
    update_button_states: Callable[[], None]


@dataclass(frozen=True)
class ManagerListUpdateSnapshot:
    """Current and desired list state for one manager update pass."""

    backing_items: list[Any]
    current_count: int
    subscribed_scope_ids: set[str]

    @property
    def expected_count(self) -> int:
        return len(self.backing_items)

    def scopes_changed(self, operations: ManagerListUpdateOperations) -> bool:
        if self.current_count != self.expected_count or self.current_count == 0:
            return True
        current_scope_ids = {
            operations.scope_for_item(item)
            for item in self.backing_items
        }
        changed = current_scope_ids != self.subscribed_scope_ids
        logger.debug(
            "FLASH_DEBUG: count=%s, current_scopes=%s, subscribed_scopes=%s, items_changed=%s",
            self.current_count,
            current_scope_ids,
            self.subscribed_scope_ids,
            changed,
        )
        return changed

    def can_update_in_place(self, operations: ManagerListUpdateOperations) -> bool:
        return (
            self.current_count == self.expected_count
            and self.current_count > 0
            and not self.scopes_changed(operations)
        )


class ManagerListUpdater:
    """Owns the list-widget update phases for manager widgets."""

    def update(self, operations: ManagerListUpdateOperations) -> None:
        if self._show_placeholder_if_needed(operations):
            return

        update_context = operations.prepare_update()
        operations.clear_scope_cache()

        preserve_selection_during_update(
            operations.item_list,
            operations.item_id,
            operations.should_preserve_selection,
            lambda: self._update_items(operations, update_context),
        )
        operations.update_button_states()

    def _show_placeholder_if_needed(self, operations: ManagerListUpdateOperations) -> bool:
        placeholder = operations.placeholder()
        if placeholder is None:
            return False

        operations.item_list.clear()
        text, data = placeholder
        placeholder_item = QListWidgetItem(text)
        placeholder_item.setData(Qt.ItemDataRole.UserRole, data)
        operations.item_list.addItem(placeholder_item)
        operations.update_button_states()
        return True

    def _update_items(self, operations: ManagerListUpdateOperations, update_context: Any) -> None:
        snapshot = ManagerListUpdateSnapshot(
            backing_items=operations.backing_items,
            current_count=operations.item_list.count(),
            subscribed_scope_ids=operations.subscribed_scope_ids(),
        )
        if snapshot.can_update_in_place(operations):
            self._update_existing_items(operations, snapshot.backing_items, update_context)
        else:
            self._rebuild_items(operations, snapshot.backing_items, update_context)
        operations.post_update()

    def _update_existing_items(
        self,
        operations: ManagerListUpdateOperations,
        backing_items: list[Any],
        update_context: Any,
    ) -> None:
        for index, item_obj in enumerate(backing_items):
            list_item = operations.item_list.item(index)
            if list_item is None:
                continue
            self._refresh_list_item(operations, list_item, item_obj, index, update_context)
            scope_id = operations.scope_for_item(item_obj)
            if scope_id and scope_id not in operations.subscribed_scope_ids():
                operations.subscribe_flash(item_obj, list_item, scope_id)

    def _rebuild_items(
        self,
        operations: ManagerListUpdateOperations,
        backing_items: list[Any],
        update_context: Any,
    ) -> None:
        operations.cleanup_flash_subscriptions()
        operations.clear_scope_to_list_item()
        operations.item_list.clear()

        for index, item_obj in enumerate(backing_items):
            display_text = operations.format_item(item_obj, index, update_context)
            list_item = QListWidgetItem(display_text)
            self._apply_item_roles(operations, list_item, item_obj, index, display_text)
            operations.item_list.addItem(list_item)
            scope_id = operations.scope_for_item(item_obj)
            operations.subscribe_flash(item_obj, list_item, scope_id)

    def _refresh_list_item(
        self,
        operations: ManagerListUpdateOperations,
        list_item: QListWidgetItem,
        item_obj: Any,
        index: int,
        update_context: Any,
    ) -> None:
        display_text = operations.format_item(item_obj, index, update_context)
        if list_item.text() != display_text:
            list_item.setText(display_text)
        self._apply_item_roles(operations, list_item, item_obj, index, display_text)

    def _apply_item_roles(
        self,
        operations: ManagerListUpdateOperations,
        list_item: QListWidgetItem,
        item_obj: Any,
        index: int,
        display_text: Any,
    ) -> None:
        list_item.setData(
            Qt.ItemDataRole.UserRole,
            operations.list_item_data_for(item_obj, index),
        )
        list_item.setToolTip(operations.tooltip_for(item_obj))
        for role_offset, value in operations.extra_data_for(item_obj, index).items():
            list_item.setData(Qt.ItemDataRole.UserRole + role_offset, value)
        operations.set_styling_roles(list_item, display_text, item_obj)
        operations.apply_scope_color(list_item, item_obj, index)
