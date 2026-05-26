"""Typed state, item-hook, and scope access for manager widgets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem

from pyqt_reactive.widgets.shared.manager_item_hooks import ManagerItemHooks
from pyqt_reactive.widgets.shared.manager_state_binding import ManagerStateBinding


@dataclass(frozen=True, slots=True)
class ManagerItemAccess:
    """Owns manager backing-list access, item codecs, and scope caching."""

    manager: Any
    scope_cache: dict[int, str]
    state_binding: ManagerStateBinding
    item_hooks: ManagerItemHooks

    @classmethod
    def from_manager(
        cls,
        manager: Any,
        scope_cache: dict[int, str],
    ) -> "ManagerItemAccess":
        binding = manager.STATE_BINDING
        if binding is None:
            raise NotImplementedError("Manager subclass must declare STATE_BINDING")

        hooks = manager.ITEM_HOOKS
        if not isinstance(hooks, ManagerItemHooks):
            raise TypeError(
                "ITEM_HOOKS must be ManagerItemHooks, "
                f"got {type(hooks).__name__}."
            )

        return cls(
            manager=manager,
            scope_cache=scope_cache,
            state_binding=binding,
            item_hooks=hooks,
        )

    def item_from_list_item(self, list_item: QListWidgetItem) -> Any:
        data = list_item.data(Qt.ItemDataRole.UserRole)
        return self.item_hooks.item_from_list_data(
            data,
            self.state_binding.items(self.manager),
        )

    def clear_scope_cache(self) -> None:
        self.scope_cache.clear()

    def scope_for_item(self, item: Any) -> str:
        item_id = id(item)
        if item_id not in self.scope_cache:
            self.scope_cache[item_id] = self.manager._get_scope_for_item(item) or ""
        return self.scope_cache[item_id]

    def list_item_scope_id(self, item: Any, index: int) -> Optional[str]:
        return self.manager._get_item_scope_id(item, index)

    def list_item_scope(self, item: Any, index: int) -> Optional[tuple[str, Any]]:
        item_type = self.manager.SCOPE_ITEM_TYPE
        if item_type is None:
            return None

        scope_id = self.list_item_scope_id(item, index)
        return (scope_id, item_type) if scope_id else None
