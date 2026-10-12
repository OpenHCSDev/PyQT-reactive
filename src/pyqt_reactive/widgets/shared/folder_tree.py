"""A folder tree built from path-like keys, usable as a table row filter."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

from PyQt6.QtCore import QSignalBlocker, Qt, pyqtSignal
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem

from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.shared.abstract_table_browser import RowFilter


class FolderSelection(ABC):
    """Which keys the tree's current selection covers."""

    @abstractmethod
    def contains(self, key: str) -> bool:
        """Whether the key lies in the selected folder."""


@dataclass(frozen=True, slots=True)
class AllFolders(FolderSelection):
    """Nothing, or the root, is selected."""

    def contains(self, key: str) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class OneFolder(FolderSelection):
    """One folder, together with its companion folders.

    A companion folder is a sibling named ``<folder><suffix>``; it has no tree
    item of its own and its keys show with the folder it accompanies.
    """

    path: str
    companion_suffixes: tuple[str, ...] = ()

    def contains(self, key: str) -> bool:
        return any(
            key.startswith(f"{self.path}{suffix}/")
            for suffix in ("", *self.companion_suffixes)
        )


class FolderTreeWidget(QTreeWidget):
    """Shows the parent folders of a set of keys; one folder can be selected."""

    folder_changed = pyqtSignal(object)
    """Emitted with the new :class:`FolderSelection` when the user picks a folder."""

    def __init__(
        self,
        color_scheme: ColorScheme | None = None,
        *,
        header: str = "Folders",
        root_label: str = "All Files",
        companion_suffixes: tuple[str, ...] = (),
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.root_label = root_label
        self.companion_suffixes = companion_suffixes
        self.setHeaderLabel(header)
        self.setMinimumWidth(150)
        self.setStyleSheet((color_scheme or ColorScheme()).styles.generate_tree_widget_style())
        self.itemSelectionChanged.connect(lambda: self.folder_changed.emit(self.selection()))

    def selection(self) -> FolderSelection:
        """The folder the user picked; :class:`AllFolders` when none is."""
        selected = self.selectedItems()
        return selected[0].data(0, Qt.ItemDataRole.UserRole) if selected else AllFolders()

    def set_keys(self, keys: Iterable[str]) -> None:
        """Rebuild the tree from the keys' parent folders, keeping the selection."""
        previous = self.selection()
        folders = sorted(
            {
                str(parent)
                for key in keys
                for parent in PurePosixPath(key).parents
                if str(parent) != "." and not self._is_companion(str(parent))
            }
        )
        with QSignalBlocker(self):
            self.clear()
            root = QTreeWidgetItem([self.root_label])
            root.setData(0, Qt.ItemDataRole.UserRole, AllFolders())
            self.addTopLevelItem(root)
            items: dict[str, QTreeWidgetItem] = {".": root}
            for folder in folders:
                path = PurePosixPath(folder)
                parent = "." if path.parent == path else str(path.parent)
                # A folder under a companion folder has no parent item and is not listed.
                if parent not in items:
                    continue
                item = QTreeWidgetItem([folder if parent == "." else path.name])
                selection = OneFolder(folder, self.companion_suffixes)
                item.setData(0, Qt.ItemDataRole.UserRole, selection)
                items[parent].addChild(item)
                items[folder] = item
                if selection == previous:
                    item.setSelected(True)
                    ancestor = item.parent()
                    while ancestor is not None:
                        ancestor.setExpanded(True)
                        ancestor = ancestor.parent()

    def _is_companion(self, folder: str) -> bool:
        return bool(self.companion_suffixes) and folder.endswith(self.companion_suffixes)


@dataclass(frozen=True, slots=True)
class FolderRowFilter(RowFilter[object]):
    """Admits the rows whose key lies in the tree's selected folder."""

    tree: FolderTreeWidget

    def admits(self, key: str, item: object) -> bool:
        return self.tree.selection().contains(key)
