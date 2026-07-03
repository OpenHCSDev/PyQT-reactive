"""Visual state, flash subscriptions, and styling roles for manager list rows."""

from __future__ import annotations

import logging
from typing import Any, Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QListWidgetItem

from objectstate import ObjectStateRegistry
from pyqt_reactive.animation import WindowFlashOverlay, create_list_item_element
from pyqt_reactive.widgets.shared.list_item_delegate import (
    DIRTY_FIELDS_ROLE,
    LAYOUT_ROLE,
    OBJECT_STATE_PATH_ROLE,
    SIG_DIFF_FIELDS_ROLE,
    StyledText,
    StyledTextLayout,
)
from pyqt_reactive.widgets.shared.scope_color_utils import get_scope_color_scheme

logger = logging.getLogger(__name__)


class ManagerListVisualState:
    """Owns row visual roles, ObjectState subscriptions, and flash geometry."""

    def __init__(self, manager: Any, scope_border_role: int, item_access: Any) -> None:
        self._manager = manager
        self._scope_border_role = scope_border_role
        self._item_access = item_access
        self._dirty_subscriptions: dict[str, tuple[Any, Any]] = {}
        self._scope_to_list_item: dict[str, QListWidgetItem] = {}
        self._pending_flash_scopes: set[str] = set()
        self._pending_changed_scope_paths: dict[str, set[str]] = {}
        self._scope_change_flush_scheduled = False
        ObjectStateRegistry.add_resolved_changed_callback(
            self._on_registry_resolved_changed
        )

    @property
    def has_navigation_items(self) -> bool:
        return bool(self._scope_to_list_item)

    def subscribed_scope_ids(self) -> set[str]:
        return set(self._scope_to_list_item.keys())

    def clear_scope_to_list_item(self) -> None:
        self._scope_to_list_item.clear()

    def subscribe_flash(
        self,
        item: Any,
        list_item: QListWidgetItem,
        scope_id: Optional[str] = None,
    ) -> None:
        if scope_id is None:
            scope_id = self._item_access.scope_for_item(item)
        logger.debug(
            "FLASH_DEBUG subscribe_flash: item=%s, scope_id=%s",
            type(item).__name__,
            scope_id,
        )
        if not scope_id:
            logger.debug("FLASH_DEBUG: No scope_id for item %s, returning", item)
            return

        self._scope_to_list_item[scope_id] = list_item

        def row_for_scope() -> int:
            row_item = self._scope_to_list_item.get(scope_id)
            if row_item is None:
                return -1
            return self._manager.item_list.row(row_item)

        element = create_list_item_element(
            scope_id,
            self._manager.item_list,
            row_for_scope,
        )
        overlay = WindowFlashOverlay.get_for_window(self._manager)
        logger.debug(
            "FLASH_DEBUG: get_for_window returned overlay=%s, window=%s",
            overlay,
            self._manager.window(),
        )
        if overlay:
            overlay.register_element(element)
            logger.debug(
                "FLASH_DEBUG: Registered element for %s, overlay has %s keys",
                scope_id,
                len(overlay._elements),
            )
        else:
            logger.debug(
                "FLASH_DEBUG: No overlay for window, cannot register list item %s",
                scope_id,
            )

        state = ObjectStateRegistry.get_by_scope(scope_id)
        logger.debug("FLASH_DEBUG: ObjectStateRegistry.get_by_scope(%s) = %s", scope_id, state)
        if not state:
            logger.debug("FLASH_DEBUG: No ObjectState for scope %s, returning", scope_id)
            return

        if scope_id not in self._dirty_subscriptions:
            def on_state_changed(_changed_paths: set[str]):
                logger.debug("DIRTY_DEBUG on_state_changed: scope=%s", scope_id)
                self._manager.queue_list_scope_visual_update(scope_id, _changed_paths)

            state.on_state_changed(on_state_changed)
            self._dirty_subscriptions[scope_id] = (state, on_state_changed)
            logger.debug("DIRTY_DEBUG: Subscribed to dirty changes for %s", scope_id)

        if scope_id in self._pending_flash_scopes:
            self._pending_flash_scopes.remove(scope_id)
            self._manager.queue_flash_batch((scope_id,))

    def cleanup(self) -> None:
        logger.debug(
            "FLASH_DEBUG cleanup: manager=%s, clearing %s list items + %s dirty subscriptions",
            type(self._manager).__name__,
            len(self._scope_to_list_item),
            len(self._dirty_subscriptions),
        )

        for scope_id in list(self._scope_to_list_item):
            overlay = WindowFlashOverlay.get_for_window(self._manager)
            if overlay:
                logger.debug("FLASH_DEBUG: Unregistering FlashElement for %s", scope_id)
                overlay.unregister_element(scope_id)

        for scope_id, (state, on_dirty_callback) in list(self._dirty_subscriptions.items()):
            try:
                state.off_state_changed(on_dirty_callback)
            except Exception as error:
                logger.debug("DIRTY_DEBUG: Error unsubscribing dirty from %s: %s", scope_id, error)

        self._dirty_subscriptions.clear()
        self._scope_to_list_item.clear()
        logger.debug("FLASH_DEBUG: Subscriptions cleared")

    def reset_context(self) -> None:
        """Clear row state and pending flashes for an explicit list-context switch."""
        self.cleanup()
        self._pending_flash_scopes.clear()
        self._pending_changed_scope_paths.clear()
        self._scope_change_flush_scheduled = False

    def dispose(self) -> None:
        """Release registry callbacks and row subscriptions for widget teardown."""
        ObjectStateRegistry.remove_resolved_changed_callback(
            self._on_registry_resolved_changed
        )
        self.reset_context()

    def _on_registry_resolved_changed(
        self,
        scope_id: str,
        changed_paths: set[str],
    ) -> None:
        self._queue_scope_changed(scope_id, changed_paths)

    def _queue_scope_changed(self, scope_id: str, changed_paths: set[str]) -> None:
        if not scope_id:
            return
        if scope_id in self._scope_to_list_item:
            self._pending_changed_scope_paths.setdefault(scope_id, set()).update(changed_paths)
            if not self._scope_change_flush_scheduled:
                self._scope_change_flush_scheduled = True
                QTimer.singleShot(0, self._flush_scope_changes)
            return
        self._pending_flash_scopes.add(scope_id)

    def _flush_scope_changes(self) -> None:
        pending = dict(self._pending_changed_scope_paths)
        self._pending_changed_scope_paths.clear()
        self._scope_change_flush_scheduled = False
        if not pending:
            return

        visible_scopes = [
            scope_id
            for scope_id in pending
            if scope_id in self._scope_to_list_item
        ]
        if not visible_scopes:
            return

        self._manager.queue_flash_batch(visible_scopes)
        for scope_id in visible_scopes:
            self._manager.queue_list_scope_visual_update(scope_id, pending[scope_id])

    def dirty_fields(self, item: Any) -> set:
        try:
            scope_id = self._item_access.scope_for_item(item)
            state = ObjectStateRegistry.get_by_scope(scope_id)
            return state.dirty_fields if state else set()
        except Exception:
            return set()

    def signature_diff_fields(self, item: Any) -> set:
        try:
            scope_id = self._item_access.scope_for_item(item)
            state = ObjectStateRegistry.get_by_scope(scope_id)
            return state.signature_diff_fields if state else set()
        except Exception:
            return set()

    def set_item_styling_roles(
        self,
        list_item: QListWidgetItem,
        display_text: Any,
        item_obj: Any,
    ) -> None:
        layout = None
        if isinstance(display_text, StyledText):
            layout = display_text.layout
        elif isinstance(display_text, StyledTextLayout):
            layout = display_text

        if layout is not None:
            self._set_item_data_if_changed(list_item, LAYOUT_ROLE, layout)
            self._set_item_data_if_changed(list_item, DIRTY_FIELDS_ROLE, self.dirty_fields(item_obj))
            self._set_item_data_if_changed(list_item, SIG_DIFF_FIELDS_ROLE, self.signature_diff_fields(item_obj))
        else:
            logger.error(
                "Cannot set LAYOUT_ROLE: display_text=%s, is_StyledText=%s",
                type(display_text),
                isinstance(display_text, StyledText),
            )

    def refresh_item_styling_roles(
        self,
        list_item: QListWidgetItem,
        item_obj: Any,
    ) -> None:
        """Refresh row state roles without rebuilding declared display text."""
        self._set_item_data_if_changed(list_item, DIRTY_FIELDS_ROLE, self.dirty_fields(item_obj))
        self._set_item_data_if_changed(list_item, SIG_DIFF_FIELDS_ROLE, self.signature_diff_fields(item_obj))

    def apply_scope_color(self, list_item: QListWidgetItem, item: Any, index: int) -> None:
        scope_info = self._list_item_scope(item, index)
        if not scope_info:
            return

        scope_id, item_type = scope_info
        scheme = get_scope_color_scheme(scope_id, step_index=index)
        bg_color = item_type.get_background_color(scheme)
        if bg_color and list_item.background().color() != bg_color:
            list_item.setBackground(bg_color)

        self._set_item_data_if_changed(list_item, self._scope_border_role, scheme)
        self._set_item_data_if_changed(list_item, OBJECT_STATE_PATH_ROLE, scope_id)

    @staticmethod
    def _set_item_data_if_changed(list_item: QListWidgetItem, role: int, value: Any) -> None:
        if list_item.data(role) != value:
            list_item.setData(role, value)

    def _list_item_scope(self, item: Any, index: int) -> Optional[tuple[str, Any]]:
        return self._item_access.list_item_scope(item, index)
