from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

from pyqt_reactive.widgets.shared.abstract_table_browser import (
    AbstractTableBrowser,
    ColumnDef,
    ColumnPresentation,
    ColumnPresentationState,
)
from pyqt_reactive.widgets.shared.column_filter_widget import (
    ColumnFilterDef,
    ColumnPresentationDialog,
    MultiColumnFilterPanel,
)
from pyqt_reactive.widgets.shared.function_table_browser import FunctionTableBrowser
from pyqt_reactive.widgets.shared.image_table_browser import ImageTableBrowser


class _ExampleTableBrowser(AbstractTableBrowser[Mapping[str, str]]):
    def __init__(
        self,
        columns: tuple[ColumnDef, ...],
        column_presentation: ColumnPresentationState,
    ) -> None:
        self._columns = columns
        super().__init__(column_presentation=column_presentation)

    def set_columns(self, columns: tuple[ColumnDef, ...]) -> None:
        self._columns = columns
        self.reconfigure_columns()

    def get_columns(self) -> list[ColumnDef]:
        return list(self._columns)

    def extract_row_data(self, item: Mapping[str, str]) -> list[str]:
        return [item.get(column.key, "") for column in self._columns]

    def get_searchable_text(self, item: Mapping[str, str]) -> str:
        return " ".join(item.values())


def _columns() -> tuple[ColumnDef, ...]:
    return (
        ColumnDef(name="Filename", key="filename"),
        ColumnDef(name="OME UUID", key="ome_UUID", filterable=True),
        ColumnDef(name="Channel", key="channel", filterable=True),
    )


def test_column_presentation_reconciles_dynamic_declarations_without_losing_stale_keys(
    qapp,
) -> None:
    preference = ColumnPresentation(
        ordered_keys=("ome_UUID", "missing", "filename"),
        hidden_keys=frozenset({"ome_UUID", "missing"}),
    )
    state = ColumnPresentationState(preference)
    state.set_columns(_columns())

    assert state.resolved_keys() == ("ome_UUID", "filename", "channel")

    state.set_columns((_columns()[0], _columns()[2]))
    assert state.resolved_keys() == ("filename", "channel")
    assert state.preference == preference

    state.set_columns(_columns())
    assert state.resolved_keys() == ("ome_UUID", "filename", "channel")
    assert not state.preference.is_visible("ome_UUID")


def test_table_header_and_filter_panels_share_keyed_order_and_visibility(qapp) -> None:
    state = ColumnPresentationState()
    browser = _ExampleTableBrowser(_columns(), state)
    browser.set_items(
        {
            "a": {"filename": "a.tif", "ome_UUID": "plate-A", "channel": "W1"},
            "b": {"filename": "b.tif", "ome_UUID": "plate-B", "channel": "W2"},
        }
    )
    panel = browser.column_filter_panel
    browser.show()
    qapp.processEvents()

    try:
        state.set_preference(
            ColumnPresentation(
                ordered_keys=("channel", "filename", "ome_UUID"),
                hidden_keys=frozenset({"ome_UUID"}),
            )
        )
        qapp.processEvents()

        header = browser.table_widget.horizontalHeader()
        columns = state.columns
        assert tuple(
            columns[header.logicalIndex(index)].key
            for index in range(header.count())
        ) == ("channel", "filename", "ome_UUID")
        assert browser.table_widget.isColumnHidden(1)
        assert tuple(panel.column_filters) == ("channel", "ome_UUID")
        assert panel.splitter.widget(0).column_key == "channel"
        assert panel.column_filters["ome_UUID"].isHidden()
    finally:
        browser.close()


def test_abstract_browser_composes_column_filters_with_external_projection(qapp) -> None:
    browser = _ExampleTableBrowser(_columns(), ColumnPresentationState())
    browser.set_items(
        {
            "a": {"filename": "a.tif", "ome_UUID": "plate-A", "channel": "W1"},
            "b": {"filename": "b.tif", "ome_UUID": "plate-B", "channel": "W2"},
            "c": {"filename": "c.tif", "ome_UUID": "plate-A", "channel": "W2"},
        }
    )
    panel = browser.column_filter_panel

    assert browser.set_column_filter_selection("ome_UUID", ("plate-A",))
    assert tuple(browser.filtered_items) == ("a", "c")

    browser.set_filtered_items(
        {"b": browser.all_items["b"], "c": browser.all_items["c"]}
    )
    assert tuple(browser.filtered_items) == ("c",)


def test_abstract_browser_stacks_context_above_same_generic_filter_panel(qapp) -> None:
    browser = _ExampleTableBrowser(_columns(), ColumnPresentationState())
    context_widget = QLabel("Domain context")

    browser.set_column_filter_context_widget(context_widget)

    assert browser.column_filter_context_widget is context_widget
    assert browser.column_filter_splitter.orientation() is Qt.Orientation.Vertical
    assert browser.column_filter_splitter.widget(0) is context_widget
    assert browser.column_filter_splitter.widget(1) is browser.column_filter_panel
    assert browser.content_splitter.orientation() is Qt.Orientation.Horizontal
    assert browser.content_splitter.widget(0) is browser.column_filter_splitter
    assert browser.content_splitter.widget(1) is browser.table_widget


def test_columns_control_remains_visible_when_filter_body_is_empty(qapp) -> None:
    browser = _ExampleTableBrowser((_columns()[0],), ColumnPresentationState())
    browser.set_items({"a": {"filename": "a.tif"}})
    browser.show()
    qapp.processEvents()

    try:
        assert browser.column_filter_panel.presentation_control.isVisible()
        assert not browser.column_filter_panel.scroll_area.isVisible()
        assert browser.column_filter_panel.column_filters == {}
    finally:
        browser.close()


def test_image_table_browser_acquires_dynamic_filters_from_column_declarations(
    qapp,
) -> None:
    browser = ImageTableBrowser()
    browser.set_metadata_keys(["ome_UUID", "channel"])
    browser.set_items(
        {
            "a": {"filename": "a.tif", "ome_UUID": "plate-A", "channel": "W1"},
            "b": {"filename": "b.tif", "ome_UUID": "plate-B", "channel": "W2"},
        }
    )

    panel = browser.column_filter_panel
    assert tuple(panel.column_filters) == ("ome_UUID", "channel")
    assert browser.set_column_filter_selection("ome_UUID", ("plate-A",))
    assert tuple(browser.filtered_items) == ("a",)


@dataclass(frozen=True)
class _FunctionRow:
    name: str
    module: str
    backend: str
    registry: str
    contract: str
    tags: tuple[str, ...]
    doc: str

    @property
    def display_name(self) -> str:
        return self.name

    def get_memory_type(self) -> str:
        return self.backend

    def get_registry_name(self) -> str:
        return self.registry


def test_function_table_browser_acquires_scalar_and_multivalue_filters(qapp) -> None:
    browser = FunctionTableBrowser()
    browser.set_items(
        {
            "core": _FunctionRow(
                "core",
                "pkg.core",
                "cpu",
                "core",
                "FLEXIBLE",
                ("segmentation", "shared"),
                "Core function",
            ),
            "plugin": _FunctionRow(
                "plugin",
                "pkg.plugin",
                "gpu",
                "plugin",
                "PURE_2D",
                ("measurement", "shared"),
                "Plugin function",
            ),
        }
    )

    panel = browser.column_filter_panel
    assert tuple(panel.column_filters) == (
        "backend",
        "registry",
        "contract",
        "tags",
    )
    assert panel.column_filters["tags"].unique_values == [
        "measurement",
        "segmentation",
        "shared",
    ]
    assert browser.set_column_filter_selection("tags", ("segmentation",))
    assert tuple(browser.filtered_items) == ("core",)


def test_semantic_filter_keys_survive_hidden_active_projection_and_rebuild(qapp) -> None:
    state = ColumnPresentationState()
    state.set_columns(_columns())
    panel = MultiColumnFilterPanel(column_presentation=state)
    specs = (
        ColumnFilterDef(_columns()[1], ("plate-A", "plate-B")),
        ColumnFilterDef(_columns()[2], ("W1", "W2")),
    )
    panel.set_column_filters(specs)
    panel.show()
    qapp.processEvents()

    try:
        panel.column_filters["ome_UUID"].set_selected_values(
            {"plate-A"},
            block_signals=True,
        )
        panel._on_filter_changed("ome_UUID")
        state.set_preference(
            ColumnPresentation(
                ordered_keys=("channel", "ome_UUID", "filename"),
                hidden_keys=frozenset({"ome_UUID"}),
            )
        )
        qapp.processEvents()

        assert panel.get_active_filters() == {"ome_UUID": {"plate-A"}}
        assert panel.hidden_active_label.text() == "1 hidden active filter"
        assert panel.hidden_active_label.isVisible()
        assert panel.hidden_active_label.toolTip() == "OME UUID"
        assert panel.apply_filters(
            [
                {"ome_UUID": "plate-A", "channel": "W1"},
                {"ome_UUID": "plate-B", "channel": "W2"},
            ]
        ) == [{"ome_UUID": "plate-A", "channel": "W1"}]

        panel.set_column_filters(
            (
                ColumnFilterDef(_columns()[1], ("plate-A", "plate-B", "plate-C")),
                ColumnFilterDef(_columns()[2], ("W1", "W2")),
            )
        )
        assert panel.column_filters["ome_UUID"].get_selected_values() == {"plate-A"}
        assert panel.get_active_filters() == {"ome_UUID": {"plate-A"}}
    finally:
        panel.close()


def test_column_editor_supports_keyboard_order_visibility_and_reset(qapp) -> None:
    state = ColumnPresentationState(
        ColumnPresentation(
            ordered_keys=("channel", "filename", "ome_UUID"),
            hidden_keys=frozenset({"ome_UUID"}),
        )
    )
    state.set_columns(_columns())
    editor = ColumnPresentationDialog(state)

    try:
        assert editor.column_list.accessibleName() == "Table columns"
        assert editor.move_up_button.accessibleName() == "Move selected column up"
        assert editor.column_list.item(0).data(Qt.ItemDataRole.UserRole) == "channel"
        editor.column_list.setCurrentRow(1)
        editor.move_up_button.click()
        assert editor.preference().ordered_keys == (
            "filename",
            "channel",
            "ome_UUID",
        )
        assert editor.preference().hidden_keys == frozenset({"ome_UUID"})

        editor.reset_button.click()
        assert editor.preference() == ColumnPresentation(
            ordered_keys=("filename", "ome_UUID", "channel"),
            hidden_keys=frozenset(),
        )
    finally:
        editor.close()


def test_column_editor_preserves_absent_dynamic_preferences(qapp) -> None:
    state = ColumnPresentationState(
        ColumnPresentation(
            ordered_keys=("ome_UUID", "missing", "filename"),
            hidden_keys=frozenset({"ome_UUID", "missing"}),
        )
    )
    state.set_columns((_columns()[0], _columns()[2]))
    editor = ColumnPresentationDialog(state)

    try:
        edited = editor.preference()
        assert edited.ordered_keys == (
            "ome_UUID",
            "missing",
            "filename",
            "channel",
        )
        assert edited.hidden_keys == frozenset({"ome_UUID", "missing"})
        state.set_preference(edited)
        state.set_columns(_columns())
        assert state.resolved_keys() == ("ome_UUID", "filename", "channel")
    finally:
        editor.close()


def test_direct_header_move_publishes_shared_order(qapp) -> None:
    state = ColumnPresentationState()
    browser = _ExampleTableBrowser(_columns(), state)
    header = browser.table_widget.horizontalHeader()

    header.moveSection(header.visualIndex(2), 0)

    assert state.preference.ordered_keys == ("channel", "filename", "ome_UUID")


def test_direct_header_move_preserves_absent_dynamic_order_preferences(qapp) -> None:
    state = ColumnPresentationState(
        ColumnPresentation(
            ordered_keys=("ome_UUID", "missing", "filename"),
            hidden_keys=frozenset({"ome_UUID"}),
        )
    )
    browser = _ExampleTableBrowser((_columns()[0], _columns()[2]), state)
    header = browser.table_widget.horizontalHeader()

    header.moveSection(header.visualIndex(1), 0)

    assert state.preference.ordered_keys == (
        "ome_UUID",
        "missing",
        "channel",
        "filename",
    )
    state.set_columns(_columns())
    assert state.resolved_keys() == ("ome_UUID", "channel", "filename")
    assert not state.preference.is_visible("ome_UUID")
