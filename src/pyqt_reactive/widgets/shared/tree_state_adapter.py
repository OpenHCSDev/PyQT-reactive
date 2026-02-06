"""Tree expansion/selection state synchronization."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Set

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem


class TreeItemKeyBuilderABC(ABC):
    """Build stable keys for tree items."""

    @abstractmethod
    def item_segment_key(self, item: QTreeWidgetItem) -> str:
        """Return one path segment for an item."""


class DictPayloadTreeItemKeyBuilder(TreeItemKeyBuilderABC):
    """Default key builder for items with dict payload metadata."""

    def item_segment_key(self, item: QTreeWidgetItem) -> str:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(data, dict):
            if "port" in data:
                return f"port:{data['port']}"
            item_type = data.get("type")
            node_id = data.get("node_id")
            if item_type is not None and node_id is not None:
                return f"{item_type}:{node_id}"
        return f"text:{item.text(0)}"


class TreeStateAdapter:
    """Capture/restore tree expansion and selection state by item keys."""

    def __init__(
        self, key_builder: TreeItemKeyBuilderABC | None = None
    ) -> None:
        self._key_builder = (
            key_builder
            if key_builder is not None
            else DictPayloadTreeItemKeyBuilder()
        )

    def item_tree_key(self, item: QTreeWidgetItem) -> str:
        segments = [self._key_builder.item_segment_key(item)]
        parent = item.parent()
        while parent is not None:
            segments.append(self._key_builder.item_segment_key(parent))
            parent = parent.parent()
        segments.reverse()
        return "/".join(segments)

    def capture_expansion_state(self, tree: QTreeWidget) -> Dict[str, bool]:
        state: Dict[str, bool] = {}

        def walk(item: QTreeWidgetItem) -> None:
            state[self.item_tree_key(item)] = item.isExpanded()
            for idx in range(item.childCount()):
                walk(item.child(idx))

        for idx in range(tree.topLevelItemCount()):
            walk(tree.topLevelItem(idx))
        return state

    def restore_expansion_state(self, tree: QTreeWidget, state: Dict[str, bool]) -> None:
        if not state:
            return

        def walk(item: QTreeWidgetItem) -> None:
            key = self.item_tree_key(item)
            if key in state:
                item.setExpanded(state[key])
            for idx in range(item.childCount()):
                walk(item.child(idx))

        for idx in range(tree.topLevelItemCount()):
            walk(tree.topLevelItem(idx))

    def capture_selected_keys(self, tree: QTreeWidget) -> Set[str]:
        return {self.item_tree_key(item) for item in tree.selectedItems()}

    def restore_selected_keys(self, tree: QTreeWidget, selected_keys: Set[str]) -> None:
        if not selected_keys:
            return

        def walk(item: QTreeWidgetItem) -> None:
            item.setSelected(self.item_tree_key(item) in selected_keys)
            for idx in range(item.childCount()):
                walk(item.child(idx))

        for idx in range(tree.topLevelItemCount()):
            walk(tree.topLevelItem(idx))
