"""Coordinate safe tree rebuilds while preserving UI state."""

from __future__ import annotations

from typing import Callable

from PyQt6.QtWidgets import QTreeWidget

from .tree_state_adapter import TreeStateAdapter


class TreeRebuildCoordinator:
    """Rebuild tree contents while preserving expansion and selection."""

    def __init__(self, state_adapter: TreeStateAdapter | None = None) -> None:
        self._state_adapter = state_adapter if state_adapter is not None else TreeStateAdapter()

    def rebuild(self, tree: QTreeWidget, rebuild_fn: Callable[[], None]) -> None:
        expansion_state = self._state_adapter.capture_expansion_state(tree)
        selected_keys = self._state_adapter.capture_selected_keys(tree)
        tree.clear()
        rebuild_fn()
        self._state_adapter.restore_expansion_state(tree, expansion_state)
        self._state_adapter.restore_selected_keys(tree, selected_keys)
