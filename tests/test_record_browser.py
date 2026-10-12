"""A record table composed with a folder tree, a grid, a panel and config actions."""

from __future__ import annotations

from dataclasses import dataclass, field

from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QSplitter

from pyqt_reactive.widgets.grid_selector import GridAddressing, GridSelectorWidget
from pyqt_reactive.widgets.shared.abstract_table_browser import ColumnDef, RowFilter
from pyqt_reactive.widgets.shared.config_action_tabs import ConfigAction, ConfigActionTabs
from pyqt_reactive.widgets.shared.detachable_panel import DetachablePanel, Docked, Floating
from pyqt_reactive.widgets.shared.folder_tree import (
    AllFolders,
    FolderRowFilter,
    FolderTreeWidget,
    OneFolder,
)
from pyqt_reactive.widgets.shared.grid_column_filter import GridColumnFilterLink
from pyqt_reactive.widgets.shared.record_table_browser import (
    LabelledValue,
    RecordTableBrowser,
    ValueLabels,
    ValueLabelSource,
)

COLUMNS = (
    ColumnDef(name="Name", key="name", width=200),
    ColumnDef(name="Cell", key="cell", filterable=True),
)

ROWS = {
    "raw/a.tif": {"name": "raw/a.tif", "cell": "A1"},
    "raw/b.tif": {"name": "raw/b.tif", "cell": "B2"},
    "raw_out/a.csv": {"name": "raw_out/a.csv", "cell": "A1"},
    "other/deep/c.tif": {"name": "other/deep/c.tif", "cell": None},
}


class CellNames(ValueLabelSource):
    """Labels the ``cell`` column; this class is the label's source."""

    def labelled(self, column_key: str, raw: str) -> LabelledValue:
        if column_key != "cell":
            return LabelledValue(column_key, raw)
        return LabelledValue(column_key, raw, label=f"cell {raw}", source=CellNames)


class LetterRowAddressing(GridAddressing):
    default_grid = (8, 12)

    def grid_index(self, value: object) -> tuple[int, int] | None:
        text = str(value)
        return (ord(text[0]) - ord("A") + 1, int(text[1:]))

    def row_label(self, row: int) -> str:
        return chr(ord("A") + row - 1)


def _table() -> RecordTableBrowser:
    table = RecordTableBrowser(value_labels=ValueLabels(CellNames()), item_noun="files")
    table.set_columns(COLUMNS)
    return table


def _tree_item(tree: FolderTreeWidget, selection: OneFolder):
    matches = [
        item
        for item in tree.findItems("*", Qt.MatchFlag.MatchWildcard | Qt.MatchFlag.MatchRecursive)
        if item.data(0, Qt.ItemDataRole.UserRole) == selection
    ]
    assert len(matches) == 1
    return matches[0]


def test_cells_show_labels_and_keep_the_declaration_that_supplied_them(qapp) -> None:
    table = _table()
    table.set_items(ROWS)

    assert table.table_widget.item(0, 1).text() == "A1 | cell A1"
    assert table.extract_row_data(ROWS["other/deep/c.tif"]) == ["other/deep/c.tif", "N/A"]
    (shown,) = table.value_labels.shown("cell", ["A1 | cell A1", "never shown"])
    assert (shown.raw, shown.label, shown.source) == ("A1", "cell A1", CellNames)
    assert table.value_labels.labelled("name", "raw/a.tif").source is None
    assert table.status_label.text() == "Showing 4/4 files"
    assert table.search_input.placeholderText() == "Search files..."


def test_search_row_filters_and_column_filters_compose(qapp) -> None:
    class OnlyTif(RowFilter):
        def admits(self, key: str, item: object) -> bool:
            return key.endswith(".tif")

    table = _table()
    table.add_row_filter(OnlyTif())
    table.set_items(ROWS)
    assert set(table.filtered_items) == {"raw/a.tif", "raw/b.tif", "other/deep/c.tif"}

    table.search_input.setText("raw")
    assert set(table.filtered_items) == {"raw/a.tif", "raw/b.tif"}

    assert table.set_column_filter_selection("cell", ("B2 | cell B2",))
    assert tuple(table.filtered_items) == ("raw/b.tif",)

    # New items keep the search text and the row filters.
    assert table.set_column_filter_selection("cell", None)
    table.set_items({key: row for key, row in ROWS.items() if key != "raw/b.tif"})
    assert tuple(table.filtered_items) == ("raw/a.tif",)


def test_folder_tree_filters_rows_and_folds_companion_folders(qapp) -> None:
    table = _table()
    tree = FolderTreeWidget(companion_suffixes=("_out",))
    table.add_row_filter(FolderRowFilter(tree))
    tree.folder_changed.connect(lambda _selection: table.apply_row_filters())
    tree.set_keys(ROWS)
    table.set_items(ROWS)

    root = tree.topLevelItem(0)
    assert root.text(0) == "All Files"
    assert [root.child(i).text(0) for i in range(root.childCount())] == ["other", "raw"]
    assert root.child(0).child(0).text(0) == "deep"
    assert tree.selection() == AllFolders()
    assert len(table.filtered_items) == 4

    raw = OneFolder("raw", ("_out",))
    _tree_item(tree, raw).setSelected(True)
    assert tree.selection() == raw
    assert set(table.filtered_items) == {"raw/a.tif", "raw/b.tif", "raw_out/a.csv"}

    # A rebuild keeps the selection while the folder still exists, then drops it.
    tree.set_keys(ROWS)
    assert tree.selection() == raw
    tree.set_keys(["other/deep/c.tif"])
    assert tree.selection() == AllFolders()


def test_reveal_path_tries_written_relative_and_unique_file_name(qapp) -> None:
    table = _table()
    table.set_items(ROWS)
    table.search_input.setText("csv")

    assert table.reveal_path("/data/plate/raw/b.tif", root="/data/plate")
    assert table.get_selected_keys() == ["raw/b.tif"]
    assert tuple(table.filtered_items) == ("raw/b.tif",)
    assert table.reveal_path("/elsewhere/c.tif")
    assert table.get_selected_keys() == ["other/deep/c.tif"]
    # Two rows are named a.tif or a.csv under different folders; "a.tif" is unique.
    assert table.reveal_path("a.tif")
    assert not table.reveal_path("/elsewhere/missing.tif")
    assert not table.reveal_path("")


def test_grid_selection_and_column_filter_stay_equal(qapp) -> None:
    table = _table()
    grid = GridSelectorWidget(addressing=LetterRowAddressing(), title="Grid", cell_noun="cells")
    link = GridColumnFilterLink(grid, table, "cell")
    table.set_items(ROWS)
    link.offer_cells()
    assert grid.model.available == {"A1", "B2"}

    grid.select_cells({"B2"})
    assert table.column_filter_selection("cell") == frozenset({"B2 | cell B2"})
    assert tuple(table.filtered_items) == ("raw/b.tif",)

    assert table.set_column_filter_selection("cell", ("A1 | cell A1",))
    assert grid.selected == {"A1"}

    # No selected cell is no filter, and no filter is no selected cell.
    grid.clear_selection()
    assert not table.is_column_filter_active("cell")
    assert grid.selected == set()
    assert len(table.filtered_items) == 4

    link.offer_cells({(2, 3): "A1", (4, 5): "B2"})
    assert grid.model.position_of_cell["B2"] == (4, 5)
    assert grid.model.dimensions == (4, 5)


def test_detachable_panel_moves_between_splitter_and_window(qapp) -> None:
    splitter = QSplitter(Qt.Orientation.Vertical)
    splitter.addWidget(QLabel("table"))
    widget = QLabel("panel")
    panel = DetachablePanel(widget, splitter, 0, "Grid View")
    shown: list[bool] = []
    panel.shown.connect(lambda: shown.append(True))
    splitter.show()

    assert splitter.indexOf(widget) == 0 and widget.isHidden()
    assert panel.toggle_button.text() == "Show Grid View"
    assert panel.placement == Docked()

    panel.toggle_button.click()
    assert not widget.isHidden() and shown == [True]
    assert panel.toggle_button.text() == "Hide Grid View"

    panel.detach()
    assert isinstance(panel.placement, Floating)
    window = panel.placement.window
    assert widget.parent() is window and splitter.indexOf(widget) == -1
    panel.detach()
    assert panel.placement.window is window

    panel.toggle_button.click()
    assert window.isHidden()
    panel.toggle_button.click()
    assert not window.isHidden()

    window.close()
    assert panel.placement == Docked()
    assert splitter.indexOf(widget) == 0 and not widget.isHidden()
    panel.reattach()
    assert panel.placement == Docked()
    splitter.close()


@dataclass
class _Target:
    enabled: bool = False
    port: int = 1


@dataclass
class _Targets:
    first: _Target = field(default_factory=_Target)
    second: _Target = field(default_factory=lambda: _Target(enabled=True))


def test_config_action_tabs_enable_buttons_from_live_state(qapp) -> None:
    set_base_config_type(_Targets)
    ObjectStateRegistry.clear()
    state = ObjectState(_Targets())
    first = ConfigAction("first", "First", "Send to First")
    second = ConfigAction("second", "Second", "Send to Second")
    tabs = ConfigActionTabs(state, (first, second))
    requested: list[ConfigAction] = []
    tabs.action_requested.connect(requested.append)

    assert [tabs.tab_widget.tabText(i) for i in range(tabs.tab_widget.count())] == [
        "First",
        "Second",
    ]
    assert tabs.enabled_actions() == (second,)
    assert not tabs.buttons[second].isEnabled()

    tabs.set_target_available(True)
    assert tabs.buttons[second].isEnabled() and not tabs.buttons[first].isEnabled()
    tabs.buttons[second].click()
    assert requested == [second]

    # An edit is live: it enables its button and becomes the saved baseline.
    state.update_parameter("first.enabled", True)
    assert state.is_raw_dirty
    tabs.parameter_changed.emit("first.enabled", True)
    assert tabs.buttons[first].isEnabled()
    assert not state.is_raw_dirty and state.dirty_fields == set()
    assert state.get_saved_resolved_value("first.enabled") is True
    tabs.close()
