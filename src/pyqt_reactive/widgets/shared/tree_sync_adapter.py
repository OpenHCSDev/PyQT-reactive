"""Generic recursive Qt tree synchronization adapter."""

from __future__ import annotations

from dataclasses import dataclass, field

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTreeWidgetItem

from pyqt_reactive.services.tree_item_key import TreeItemKeyProviderABC


@dataclass
class TreeNode:
    """Generic tree node model for Qt tree widgets."""

    node_id: str
    node_type: str
    label: str
    status: str
    info: str
    children: list[TreeNode] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TreeNodeIdentity(TreeItemKeyProviderABC):
    """Stable typed identity stored in a Qt tree item."""

    node_type: str
    node_id: str

    def tree_item_key(self) -> str:
        return f"{self.node_type}:{self.node_id}"


class TreeSyncAdapter:
    """Sync typed node trees to QTreeWidgetItem hierarchies."""

    def sync_children(
        self,
        parent_item: QTreeWidgetItem,
        nodes: list[TreeNode],
    ) -> None:
        seen: set[TreeNodeIdentity] = set()
        for node in nodes:
            identity = TreeNodeIdentity(node_type=node.node_type, node_id=node.node_id)
            seen.add(identity)
            child = self._find_child(parent_item, node.node_type, node.node_id)
            if child is None:
                child = QTreeWidgetItem([node.label, node.status, node.info])
                child.setData(0, Qt.ItemDataRole.UserRole, identity)
                parent_item.addChild(child)
            else:
                child.setText(0, node.label)
                child.setText(1, node.status)
                child.setText(2, node.info)

            self.sync_children(child, node.children)

        for idx in range(parent_item.childCount() - 1, -1, -1):
            existing = parent_item.child(idx)
            identity = existing.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(identity, TreeNodeIdentity):
                continue
            if identity not in seen:
                parent_item.removeChild(existing)

    def _find_child(
        self,
        parent_item: QTreeWidgetItem,
        node_type: str,
        node_id: str,
    ) -> QTreeWidgetItem | None:
        for idx in range(parent_item.childCount()):
            candidate = parent_item.child(idx)
            identity = candidate.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(identity, TreeNodeIdentity):
                continue
            if identity.node_type != node_type:
                continue
            if identity.node_id != node_id:
                continue
            return candidate
        return None
