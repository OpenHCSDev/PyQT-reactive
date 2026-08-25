"""Tests for generic QWidget tree projection."""

import pytest
from PyQt6.QtCore import QStringListModel
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTabBar,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pyqt_reactive.services.widget_tree_projection import (
    DEFAULT_WIDGET_DESCRIPTOR_PROJECTOR_REGISTRY,
    WidgetActionKind,
    WidgetActionTargetInvalidError,
    WidgetDescriptor,
    WidgetTreeProjectionPolicy,
    WidgetTreeProjectionService,
)
from pyqt_reactive.widgets.shared.list_item_delegate import LAYOUT_ROLE
from pyqt_reactive.widgets.shared.styled_text_layout import (
    Segment,
    StyledText,
    StyledTextLayout,
)


def _descriptors_by_name(descriptor: WidgetDescriptor) -> dict[str, WidgetDescriptor]:
    descriptors: dict[str, WidgetDescriptor] = {}
    if descriptor.object_name != "":
        descriptors[descriptor.object_name] = descriptor

    for child in descriptor.children:
        descriptors.update(_descriptors_by_name(child))

    return descriptors


def _descriptors_by_class(
    descriptor: WidgetDescriptor,
    class_name: str,
) -> list[WidgetDescriptor]:
    descriptors = [descriptor] if descriptor.class_name == class_name else []
    for child in descriptor.children:
        descriptors.extend(_descriptors_by_class(child, class_name))
    return descriptors


class _ProjectionCountingLabel(QLabel):
    """Expose whether a widget family projector visited this label."""

    def __init__(self, text: str, parent: QWidget) -> None:
        super().__init__(text, parent)
        self.projection_reads = 0

    def text(self) -> str:
        self.projection_reads += 1
        return super().text()


def test_widget_tree_projection_describes_known_widget_families(qapp) -> None:
    root = QWidget()
    root.setObjectName("root_widget")
    root.setWindowTitle("Root Window")

    layout = QVBoxLayout(root)

    label = QLabel("Plate status")
    label.setObjectName("status_label")
    layout.addWidget(label)

    button = QPushButton("Compile")
    button.setObjectName("compile_button")
    button.setToolTip("Compile selected plate")
    button.setStatusTip("Compile operation")
    button.setCheckable(True)
    button.setChecked(True)
    layout.addWidget(button)

    combo = QComboBox()
    combo.setObjectName("plate_selector")
    combo.addItems(("start", "final"))
    combo.setCurrentIndex(1)
    layout.addWidget(combo)

    line_edit = QLineEdit("well_filter=2")
    line_edit.setObjectName("config_line")
    layout.addWidget(line_edit)

    spin_box = QSpinBox()
    spin_box.setObjectName("batch_size")
    spin_box.setValue(7)
    layout.addWidget(spin_box)

    group_box = QGroupBox("Streaming")
    group_box.setObjectName("streaming_group")
    group_box.setCheckable(True)
    group_box.setChecked(False)
    layout.addWidget(group_box)

    tab_widget = QTabWidget()
    tab_widget.setObjectName("editor_tabs")
    tab_widget.addTab(QWidget(), "Visual")
    tab_widget.addTab(QWidget(), "Code")
    tab_widget.setCurrentIndex(1)
    layout.addWidget(tab_widget)

    tab_bar = QTabBar()
    tab_bar.setObjectName("editor_tab_bar")
    tab_bar.addTab("Step Settings")
    tab_bar.addTab("Function Pattern")
    tab_bar.addTab("Artifacts")
    tab_bar.setCurrentIndex(2)
    layout.addWidget(tab_bar)

    root.show()
    qapp.processEvents()

    projection = WidgetTreeProjectionService.project(root)
    descriptors = _descriptors_by_name(projection.root)

    assert projection.root.path == ()
    assert projection.root.path_id == "root"
    assert projection.root.class_name == "QWidget"
    assert projection.root.object_name == "root_widget"
    assert projection.root.window_title == "Root Window"
    assert projection.widget_count >= 8
    assert projection.actionable_count >= 5

    assert descriptors["status_label"].path == (0,)
    assert descriptors["status_label"].path_id == "0"
    assert descriptors["status_label"].text == "Plate status"

    compile_button = descriptors["compile_button"]
    assert compile_button.text == "Compile"
    assert compile_button.clickable
    assert compile_button.actionable
    assert compile_button.checkable
    assert compile_button.checked
    assert compile_button.tool_tip == "Compile selected plate"
    assert compile_button.status_tip == "Compile operation"
    assert compile_button.action_kinds == (
        WidgetActionKind.BUTTON,
        WidgetActionKind.CHECKABLE,
    )

    plate_selector = descriptors["plate_selector"]
    assert plate_selector.current_index == 1
    assert plate_selector.current_text == "final"
    assert plate_selector.item_count == 2
    assert plate_selector.action_kinds == (WidgetActionKind.CHOICE,)

    config_line = descriptors["config_line"]
    assert config_line.text == "well_filter=2"
    assert config_line.action_kinds == (WidgetActionKind.TEXT_INPUT,)

    batch_size = descriptors["batch_size"]
    assert batch_size.text == "7"
    assert batch_size.action_kinds == (WidgetActionKind.SPIN_INPUT,)

    streaming_group = descriptors["streaming_group"]
    assert streaming_group.title == "Streaming"
    assert streaming_group.checkable
    assert streaming_group.checked is False

    editor_tabs = descriptors["editor_tabs"]
    assert editor_tabs.current_index == 1
    assert editor_tabs.current_text == "Code"
    assert editor_tabs.item_count == 2
    assert editor_tabs.item_texts == ("Visual", "Code")
    assert editor_tabs.action_kinds == (WidgetActionKind.TAB_SELECTOR,)

    editor_tab_bar = descriptors["editor_tab_bar"]
    assert editor_tab_bar.current_index == 2
    assert editor_tab_bar.current_text == "Artifacts"
    assert editor_tab_bar.item_count == 3
    assert editor_tab_bar.item_texts == (
        "Step Settings",
        "Function Pattern",
        "Artifacts",
    )
    assert editor_tab_bar.action_kinds == (WidgetActionKind.TAB_SELECTOR,)


def test_nominal_widget_projectors_own_indexed_selection(qapp) -> None:
    combo = QComboBox()
    combo.addItems(("main", "server"))
    tab_bar = QTabBar()
    tab_bar.addTab("Status")
    tab_bar.addTab("Logs")

    registry = DEFAULT_WIDGET_DESCRIPTOR_PROJECTOR_REGISTRY

    registry.projector_for(combo).invoke_action(
        combo,
        WidgetActionKind.CHOICE,
        target_index=1,
    )
    qapp.processEvents()
    assert combo.currentText() == "server"

    registry.projector_for(tab_bar).invoke_action(
        tab_bar,
        WidgetActionKind.TAB_SELECTOR,
        target_index=1,
    )
    qapp.processEvents()
    assert tab_bar.currentIndex() == 1

    with pytest.raises(WidgetActionTargetInvalidError):
        registry.projector_for(combo).invoke_action(
            combo,
            WidgetActionKind.CHOICE,
            target_index=2,
        )


def test_widget_projector_registry_resolves_qt_mro(qapp) -> None:
    check_box = QCheckBox("Enabled")
    check_box.setObjectName("enabled_box")
    check_box.setChecked(True)

    projection = WidgetTreeProjectionService.project(check_box)

    assert projection.root.object_name == "enabled_box"
    assert projection.root.text == "Enabled"
    assert projection.root.checkable
    assert projection.root.checked
    assert projection.root.action_kinds == (
        WidgetActionKind.BUTTON,
        WidgetActionKind.CHECKABLE,
    )


def test_widget_text_projection_policy_truncates_explicitly(qapp) -> None:
    line_edit = QLineEdit("abcdefghijklmnopqrstuvwxyz")
    policy = WidgetTreeProjectionPolicy(maximum_text_length=10, truncation_suffix="...")

    projection = WidgetTreeProjectionService.project(line_edit, policy=policy)

    assert projection.root.text == "abcdefg..."
    assert projection.root.text_truncated


def test_widget_tree_node_bound_stops_live_projection(qapp) -> None:
    root = QWidget()
    labels = tuple(_ProjectionCountingLabel(str(index), root) for index in range(6))

    projection = WidgetTreeProjectionService.project(
        root,
        policy=WidgetTreeProjectionPolicy(maximum_nodes=3),
    )

    assert projection.widget_count == 3
    assert len(projection.root.children) == 2
    assert projection.truncated
    assert [label.projection_reads for label in labels] == [1, 1, 0, 0, 0, 0]


def test_bounded_widget_tree_projects_visible_siblings_before_hidden_siblings(
    qapp,
) -> None:
    root = QWidget()
    hidden = _ProjectionCountingLabel("hidden", root)
    visible = _ProjectionCountingLabel("visible", root)
    root.show()
    hidden.hide()
    qapp.processEvents()

    projection = WidgetTreeProjectionService.project(
        root,
        policy=WidgetTreeProjectionPolicy(maximum_nodes=2),
    )

    assert projection.root.children[0].text == "visible"
    assert projection.root.children[0].path == (1,)
    assert projection.root.child_at_index(1) is projection.root.children[0]
    assert projection.root.child_at_index(0) is None
    assert visible.projection_reads == 1
    assert hidden.projection_reads == 0


def test_widget_tree_depth_bound_stops_live_projection(qapp) -> None:
    root = QWidget()
    branch = QWidget(root)
    leaf = _ProjectionCountingLabel("unvisited", branch)

    projection = WidgetTreeProjectionService.project(
        root,
        policy=WidgetTreeProjectionPolicy(maximum_depth=1),
    )

    assert projection.widget_count == 2
    assert len(projection.root.children) == 1
    assert projection.root.children[0].children == ()
    assert projection.truncated
    assert leaf.projection_reads == 0


def test_default_widget_tree_policy_projects_the_complete_tree(qapp) -> None:
    root = QWidget()
    labels = tuple(_ProjectionCountingLabel(str(index), root) for index in range(6))

    projection = WidgetTreeProjectionService.project(root)

    assert projection.widget_count == 7
    assert not projection.truncated
    assert [label.projection_reads for label in labels] == [1, 1, 1, 1, 1, 1]


@pytest.mark.parametrize(
    ("field", "value"),
    (("maximum_depth", -1), ("maximum_nodes", 0)),
)
def test_widget_tree_policy_rejects_invalid_traversal_bounds(field, value) -> None:
    with pytest.raises(ValueError):
        WidgetTreeProjectionPolicy(**{field: value})


def test_widget_tree_projection_includes_item_view_model_rows(qapp) -> None:
    tree = QTreeWidget()
    tree.setObjectName("config_hierarchy")
    tree.setHeaderLabels(("Configuration",))

    root_item = QTreeWidgetItem(("RootConfig",))
    well_filter_item = QTreeWidgetItem(("* Well Filter Config",))
    well_filter_item.addChild(QTreeWidgetItem(("well_filter",)))
    root_item.addChild(well_filter_item)
    root_item.addChild(QTreeWidgetItem(("Napari Streaming Config",)))
    tree.addTopLevelItem(root_item)
    tree.expandAll()
    tree.show()
    qapp.processEvents()

    projection = WidgetTreeProjectionService.project(tree)

    assert projection.root.class_name == "QTreeWidget"
    assert projection.root.item_count == 1
    model_rows = _descriptors_by_class(projection.root, "QModelIndex")
    root_row = next(row for row in model_rows if row.text == "RootConfig")
    assert [child.text for child in root_row.children] == [
        "* Well Filter Config",
        "Napari Streaming Config",
    ]
    assert root_row.children[0].children[0].text == "well_filter"
    assert root_row.action_kinds == (WidgetActionKind.ITEM_SELECT,)
    assert root_row.clickable
    assert root_row.actionable


def test_item_model_bound_marks_the_tree_projection_truncated(qapp) -> None:
    tree = QTreeWidget()
    tree.setHeaderLabels(("Functions",))
    tree.addTopLevelItems(
        tuple(QTreeWidgetItem((name,)) for name in ("load", "segment", "measure"))
    )

    projection = WidgetTreeProjectionService.project(
        tree,
        policy=WidgetTreeProjectionPolicy(maximum_item_model_nodes=1),
    )

    model_rows = _descriptors_by_class(projection.root, "QModelIndex")
    limits = _descriptors_by_class(projection.root, "QModelIndexLimit")
    assert [row.text for row in model_rows] == ["load"]
    assert len(limits) == 1
    assert projection.truncated


def test_widget_tree_projection_handles_list_models_without_public_column_count(qapp) -> None:
    combo = QComboBox()
    combo.setObjectName("function_selector")
    combo.setModel(QStringListModel(["load_image", "segment_cells"]))

    projection = WidgetTreeProjectionService.project(combo)

    model_rows = _descriptors_by_class(projection.root, "QModelIndex")
    assert [row.text for row in model_rows] == ["load_image", "segment_cells"]


def test_widget_tree_projection_uses_structured_list_item_layout(qapp) -> None:
    item_list = QListWidget()
    item_list.setObjectName("pipeline_steps")
    layout = StyledTextLayout(
        name=Segment("Agent invert"),
        detail_line="/tmp/plate",
        preview_segments=[Segment("workers=1"), Segment("memory")],
        config_segments=[Segment("NAP")],
        multiline=True,
    )
    item = QListWidgetItem(StyledText(layout))
    item.setData(LAYOUT_ROLE, layout)
    item_list.addItem(item)
    item_list.show()
    qapp.processEvents()

    projection = WidgetTreeProjectionService.project(item_list)

    model_rows = _descriptors_by_class(projection.root, "QModelIndex")
    assert [row.text for row in model_rows] == [
        "Agent invert | /tmp/plate | workers=1 | memory | configs=[NAP]"
    ]
    assert model_rows[0].action_kinds == (WidgetActionKind.ITEM_SELECT,)
    assert model_rows[0].current_index == 0
    assert model_rows[0].current_text == (
        "Agent invert | /tmp/plate | workers=1 | memory | configs=[NAP]"
    )
