"""Nominal contracts used by configuration hierarchy tree widgets."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QTreeWidget

from pyqt_reactive.widgets.shared.scope_visual_config import ScopeColorScheme


class ScopeColorSchemeHost:
    """Widget/window that owns a scope color scheme."""

    _scope_color_scheme: ScopeColorScheme | None


class TreeFlashColorProvider(ABC):
    """Provides precomputed flash colors for config tree delegates."""

    @abstractmethod
    def get_flash_color_for_key(self, key: str) -> Optional[QColor]:
        """Return the current flash color for a scoped key."""
        ...


class ConfigTreeFlashManager(TreeFlashColorProvider):
    """Full flash/dirty contract required by ConfigHierarchyTreeHelper."""

    _on_build_complete_callbacks: list[Callable[[], None]]

    @abstractmethod
    def _get_scoped_flash_key(self, key: str) -> str:
        """Return the scoped flash key used by the flash coordinator."""
        ...

    @abstractmethod
    def register_flash_tree_item(
        self,
        key: str,
        tree: QTreeWidget,
        get_index: Callable[[], Any],
    ) -> None:
        """Register a tree item with the flash coordinator."""
        ...

    @abstractmethod
    def update_groupbox_dirty_markers(
        self,
        dirty_prefixes: set[str],
        sig_diff_prefixes: set[str],
    ) -> None:
        """Synchronize groupbox dirty markers with tree dirty state."""
        ...

    @abstractmethod
    def register_repaint_callback(self, callback: Callable[[], None]) -> None:
        """Register a repaint callback used during flash animation."""
        ...
