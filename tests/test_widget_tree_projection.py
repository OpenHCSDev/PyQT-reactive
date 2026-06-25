"""Tests for generic QWidget tree projection."""

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pyqt_reactive.services.widget_tree_projection import (
    WidgetActionKind,
    WidgetDescriptor,
    WidgetTreeProjectionPolicy,
    WidgetTreeProjectionService,
)


def _descriptors_by_name(descriptor: WidgetDescriptor) -> dict[str, WidgetDescriptor]:
    descriptors: dict[str, WidgetDescriptor] = {}
    if descriptor.object_name != "":
        descriptors[descriptor.object_name] = descriptor

    for child in descriptor.children:
        descriptors.update(_descriptors_by_name(child))

    return descriptors


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
    assert editor_tabs.action_kinds == (WidgetActionKind.TAB_SELECTOR,)


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
