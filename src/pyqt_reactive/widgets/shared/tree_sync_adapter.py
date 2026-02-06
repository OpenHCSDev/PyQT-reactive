"""Generic recursive Qt tree synchronization adapter."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTreeWidgetItem


@dataclass
class TreeNode:
    """Generic tree node model for Qt tree widgets."""

    node_id: str
    node_type: str
    label: str
    status: str
    info: str
    children: List["TreeNode"] = field(default_factory=list)


class TreeSyncAdapter:
    """Sync typed node trees to QTreeWidgetItem hierarchies."""

    _TYPE_KEY = "type"
    _NODE_ID_KEY = "node_id"

    def sync_children(self, parent_item: QTreeWidgetItem, nodes: List[TreeNode]) -> None:
        seen: set[tuple[str, str]] = set()
        for node in nodes:
            key = (node.node_type, node.node_id)
            seen.add(key)
            child = self._find_child(parent_item, node.node_type, node.node_id)
            if child is None:
                child = QTreeWidgetItem([node.label, node.status, node.info])
                child.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    {
                        self._TYPE_KEY: node.node_type,
                        self._NODE_ID_KEY: node.node_id,
                    },
                )
                parent_item.addChild(child)
            else:
                child.setText(0, node.label)
                child.setText(1, node.status)
                child.setText(2, node.info)

            self.sync_children(child, node.children)

        for idx in range(parent_item.childCount() - 1, -1, -1):
            existing = parent_item.child(idx)
            payload = existing.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(payload, dict):
                continue
            existing_key = (
                payload.get(self._TYPE_KEY, ""),
                payload.get(self._NODE_ID_KEY, ""),
            )
            if existing_key not in seen:
                parent_item.removeChild(existing)

    def _find_child(
        self,
        parent_item: QTreeWidgetItem,
        node_type: str,
        node_id: str,
    ) -> QTreeWidgetItem | None:
        for idx in range(parent_item.childCount()):
            candidate = parent_item.child(idx)
            payload = candidate.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(payload, dict):
                continue
            if payload.get(self._TYPE_KEY) != node_type:
                continue
            if payload.get(self._NODE_ID_KEY) != node_id:
                continue
            return candidate
        return None
