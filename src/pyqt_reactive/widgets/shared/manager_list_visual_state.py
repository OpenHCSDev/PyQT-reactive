"""Qt visual state, flash subscriptions, and styling roles over formbridge.managers."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

from formbridge.managers.scope_visual_tracker import (
    ManagerScopeVisualTracker,
    ManagerVisualSurface,
)
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QListWidgetItem

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


class ManagerListVisualState(ManagerScopeVisualTracker, ManagerVisualSurface):
    """Qt manager list visual state inheriting formbridge's ObjectState/flash tracker."""

    def __init__(self, manager: Any, scope_border_role: int, item_access: Any) -> None:
        self._manager = manager
        self._scope_border_role = scope_border_role
        self._item_access = item_access
        self._scope_to_list_item: dict[str, QListWidgetItem] = {}
        super().__init__(self)

    def schedule_flush(self, callback: Callable[[], None]) -> None:
        QTimer.singleShot(0, callback)

    def on_scope_visual_update(self, scope_id: str, changed_paths: set[str]) -> None:
        self._manager.queue_list_scope_visual_update(scope_id, changed_paths)

    def on_flash_batch(self, scope_ids: Sequence[str]) -> None:
        self._manager.queue_flash_batch(tuple(scope_ids))

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
        scope_id: str | None = None,
    ) -> None:
        if scope_id is None:
            scope_id = self._item_access.scope_for_item(item)
        if not scope_id:
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
        if overlay:
            overlay.register_element(element)

        self.subscribe_scope(scope_id)

    def cleanup(self) -> None:
        for scope_id in list(self._scope_to_list_item):
            overlay = WindowFlashOverlay.get_for_window(self._manager)
            if overlay:
                overlay.unregister_element(scope_id)

        super().cleanup()
        self._scope_to_list_item.clear()

    def dirty_fields(self, item: Any) -> set:
        try:
            scope_id = self._item_access.scope_for_item(item)
            return super().dirty_fields(scope_id)
        except Exception:
            return set()

    def signature_diff_fields(self, item: Any) -> set:
        try:
            scope_id = self._item_access.scope_for_item(item)
            return super().signature_diff_fields(scope_id)
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
            self._set_item_data_if_changed(
                list_item, DIRTY_FIELDS_ROLE, self.dirty_fields(item_obj)
            )
            self._set_item_data_if_changed(
                list_item, SIG_DIFF_FIELDS_ROLE, self.signature_diff_fields(item_obj)
            )
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
        self._set_item_data_if_changed(
            list_item, SIG_DIFF_FIELDS_ROLE, self.signature_diff_fields(item_obj)
        )

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

    def _list_item_scope(self, item: Any, index: int) -> tuple[str, Any] | None:
        return self._item_access.list_item_scope(item, index)
