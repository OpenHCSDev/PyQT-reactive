"""Visual state, flash subscriptions, and styling roles for manager list rows."""

from __future__ import annotations

import logging
from typing import Any, Optional

from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QListWidgetItem, QWidget

from objectstate import ObjectStateRegistry
from pyqt_reactive.animation import FlashElement, WindowFlashOverlay
from pyqt_reactive.widgets.shared.list_item_delegate import (
    DIRTY_FIELDS_ROLE,
    FLASH_KEY_ROLE,
    LAYOUT_ROLE,
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
        self._flash_subscriptions: dict[str, tuple[Any, Any]] = {}
        self._dirty_subscriptions: dict[str, tuple[Any, Any]] = {}
        self._scope_to_list_item: dict[str, QListWidgetItem] = {}

    @property
    def has_navigation_items(self) -> bool:
        return bool(self._scope_to_list_item)

    def subscribed_scope_ids(self) -> set[str]:
        return set(self._flash_subscriptions.keys())

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
        if scope_id in self._flash_subscriptions:
            logger.debug("FLASH_DEBUG: Already subscribed to %s, skipping", scope_id)
            return

        element = FlashElement(
            key=scope_id,
            get_rect_in_window=lambda window: self._list_item_rect(scope_id, window),
            needs_scroll_clipping=False,
            source_id=f"list_item:{id(self._manager)}:{scope_id}",
            skip_overlay_paint=True,
            delegate_widget=self._manager.item_list,
            get_model_index=lambda: self._model_index(scope_id),
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

        def on_change(changed_paths):
            logger.debug(
                "FLASH_DEBUG on_change CALLBACK FIRED: scope=%s, paths=%s",
                scope_id,
                changed_paths,
            )
            self._manager.queue_flash(scope_id)
            self._manager.queue_visual_update()

        state.on_resolved_changed(on_change)
        self._flash_subscriptions[scope_id] = (state, on_change)
        logger.debug(
            "FLASH_DEBUG: Subscribed to %s, total subscriptions=%s",
            scope_id,
            len(self._flash_subscriptions),
        )

        if scope_id not in self._dirty_subscriptions:
            def on_state_changed():
                logger.debug("DIRTY_DEBUG on_state_changed: scope=%s", scope_id)
                self._manager.queue_visual_update()

            state.on_state_changed(on_state_changed)
            self._dirty_subscriptions[scope_id] = (state, on_state_changed)
            logger.debug("DIRTY_DEBUG: Subscribed to dirty changes for %s", scope_id)

    def cleanup(self) -> None:
        logger.debug(
            "FLASH_DEBUG cleanup: manager=%s, clearing %s flash + %s dirty subscriptions",
            type(self._manager).__name__,
            len(self._flash_subscriptions),
            len(self._dirty_subscriptions),
        )

        for scope_id, (state, on_change_callback) in list(self._flash_subscriptions.items()):
            logger.debug("FLASH_DEBUG: Unsubscribing from %s", scope_id)
            try:
                state.off_resolved_changed(on_change_callback)
            except Exception as error:
                logger.debug("FLASH_DEBUG: Error unsubscribing from %s: %s", scope_id, error)

            overlay = WindowFlashOverlay.get_for_window(self._manager)
            if overlay:
                logger.debug("FLASH_DEBUG: Unregistering FlashElement for %s", scope_id)
                overlay.unregister_element(scope_id)

        for scope_id, (state, on_dirty_callback) in list(self._dirty_subscriptions.items()):
            try:
                state.off_state_changed(on_dirty_callback)
            except Exception as error:
                logger.debug("DIRTY_DEBUG: Error unsubscribing dirty from %s: %s", scope_id, error)

        self._flash_subscriptions.clear()
        self._dirty_subscriptions.clear()
        self._scope_to_list_item.clear()
        logger.debug("FLASH_DEBUG: Subscriptions cleared")

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
            list_item.setData(LAYOUT_ROLE, layout)
            list_item.setData(DIRTY_FIELDS_ROLE, self.dirty_fields(item_obj))
            list_item.setData(SIG_DIFF_FIELDS_ROLE, self.signature_diff_fields(item_obj))
        else:
            logger.error(
                "Cannot set LAYOUT_ROLE: display_text=%s, is_StyledText=%s",
                type(display_text),
                isinstance(display_text, StyledText),
            )

    def apply_scope_color(self, list_item: QListWidgetItem, item: Any, index: int) -> None:
        scope_info = self._list_item_scope(item, index)
        if not scope_info:
            return

        scope_id, item_type = scope_info
        scheme = get_scope_color_scheme(scope_id, step_index=index)
        bg_color = item_type.get_background_color(scheme)
        if bg_color:
            list_item.setBackground(bg_color)

        list_item.setData(self._scope_border_role, scheme)
        list_item.setData(FLASH_KEY_ROLE, scope_id)

    def _list_item_scope(self, item: Any, index: int) -> Optional[tuple[str, Any]]:
        return self._item_access.list_item_scope(item, index)

    def _list_item_rect(self, scope_id: str, window: QWidget) -> Optional[QRect]:
        if scope_id not in self._scope_to_list_item:
            logger.debug(
                "FLASH_DEBUG list_item_rect: scope_id %s not in scope map (has %s keys)",
                scope_id,
                len(self._scope_to_list_item),
            )
            return None
        item = self._scope_to_list_item[scope_id]
        if item is None:
            logger.debug("FLASH_DEBUG list_item_rect: item is None for %s", scope_id)
            return None

        visual_rect = self._manager.item_list.visualItemRect(item)
        if visual_rect.isEmpty():
            logger.debug("FLASH_DEBUG list_item_rect: visual_rect is empty for %s", scope_id)
            return None

        viewport = self._manager.item_list.viewport()
        if viewport is None:
            logger.debug("FLASH_DEBUG list_item_rect: viewport is None for %s", scope_id)
            return None

        clipped_rect = visual_rect.intersected(viewport.rect())
        if clipped_rect.isEmpty():
            logger.debug("FLASH_DEBUG list_item_rect: clipped_rect is empty for %s", scope_id)
            return None

        global_pos = viewport.mapToGlobal(clipped_rect.topLeft())
        local_pos = window.mapFromGlobal(global_pos)
        result = QRect(local_pos, clipped_rect.size())
        logger.debug("FLASH_DEBUG list_item_rect: SUCCESS for %s, rect=%s", scope_id, result)
        return result

    def _model_index(self, scope_id: str):
        if scope_id not in self._scope_to_list_item:
            return None
        item = self._scope_to_list_item[scope_id]
        if item is None:
            return None
        return self._manager.item_list.indexFromItem(item)
