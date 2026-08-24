"""Tree expansion/selection state synchronization."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem

from pyqt_reactive.services.tree_item_key import TreeItemKeyProviderABC


class TreeItemKeyBuilderABC(ABC):
    """Build stable keys for tree items."""

    @abstractmethod
    def item_segment_key(self, item: QTreeWidgetItem) -> str:
        """Return one path segment for an item."""


class TypedPayloadTreeItemKeyBuilder(TreeItemKeyBuilderABC):
    """Default key builder for nominal item payloads."""

    def item_segment_key(self, item: QTreeWidgetItem) -> str:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(data, TreeItemKeyProviderABC):
            return data.tree_item_key()
        return f"text:{item.text(0)}"


class TreeStateAdapter:
    """Capture/restore tree expansion and selection state by item keys."""

    def __init__(self, key_builder: TreeItemKeyBuilderABC) -> None:
        self._key_builder = key_builder

    @classmethod
    def default(cls) -> TreeStateAdapter:
        """Build the default typed-payload tree state adapter."""
        return cls(TypedPayloadTreeItemKeyBuilder())

    def item_tree_key(self, item: QTreeWidgetItem) -> str:
        segments = [self._key_builder.item_segment_key(item)]
        parent = item.parent()
        while parent is not None:
            segments.append(self._key_builder.item_segment_key(parent))
            parent = parent.parent()
        segments.reverse()
        return "/".join(segments)

    @staticmethod
    def _subtree_items(
        roots: Iterable[QTreeWidgetItem],
    ) -> Iterator[QTreeWidgetItem]:
        pending = list(reversed(tuple(roots)))
        while pending:
            item = pending.pop()
            yield item
            pending.extend(item.child(index) for index in reversed(range(item.childCount())))

    def capture_subtree_expansion_state(
        self,
        roots: Iterable[QTreeWidgetItem],
    ) -> dict[str, bool]:
        """Capture expansion state beneath the supplied item roots."""

        return {self.item_tree_key(item): item.isExpanded() for item in self._subtree_items(roots)}

    def restore_subtree_expansion_state(
        self,
        roots: Iterable[QTreeWidgetItem],
        state: dict[str, bool],
        *,
        default_expanded: bool | None = None,
    ) -> None:
        """Restore known items and optionally default newly introduced items."""

        for item in self._subtree_items(roots):
            key = self.item_tree_key(item)
            if key in state:
                item.setExpanded(state[key])
            elif default_expanded is not None:
                item.setExpanded(default_expanded)

    def capture_expansion_state(self, tree: QTreeWidget) -> dict[str, bool]:
        return self.capture_subtree_expansion_state(
            tree.topLevelItem(index) for index in range(tree.topLevelItemCount())
        )

    def restore_expansion_state(self, tree: QTreeWidget, state: dict[str, bool]) -> None:
        if not state:
            return
        self.restore_subtree_expansion_state(
            (tree.topLevelItem(index) for index in range(tree.topLevelItemCount())),
            state,
        )

    def capture_selected_keys(self, tree: QTreeWidget) -> set[str]:
        return {self.item_tree_key(item) for item in tree.selectedItems()}

    def restore_selected_keys(self, tree: QTreeWidget, selected_keys: set[str]) -> None:
        if not selected_keys:
            return
        for item in self._subtree_items(
            tree.topLevelItem(index) for index in range(tree.topLevelItemCount())
        ):
            item.setSelected(self.item_tree_key(item) in selected_keys)
