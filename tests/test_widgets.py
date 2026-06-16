"""Tests for extended widgets."""

from enum import Enum
import pytest


def test_no_scroll_spinbox(qapp):
    """Test NoScrollSpinBox creation."""
    from pyqt_reactive.widgets import NoScrollSpinBox
    
    widget = NoScrollSpinBox()
    assert widget is not None


def test_none_aware_checkbox(qapp):
    """Test NoneAwareCheckBox creation."""
    from pyqt_reactive.widgets import NoneAwareCheckBox

    widget = NoneAwareCheckBox()
    assert widget is not None


def test_none_aware_checkbox_toggle_commits_placeholder(qapp):
    """Programmatic title toggles commit inherited checkbox values."""
    from pyqt_reactive.widgets import NoneAwareCheckBox

    widget = NoneAwareCheckBox()
    widget.set_placeholder_preview(False)

    values = []
    widget.connect_change_signal(values.append)

    widget.toggle()

    assert values[-1] is True
    assert widget.get_value() is True
    assert not widget.is_placeholder()


def test_enum_union_uses_enum_widget(qapp):
    """Enum unions retain the closed-domain enum widget."""
    from PyQt6.QtWidgets import QComboBox
    from pyqt_reactive.forms.widget_strategies import create_pyqt6_widget

    class Mode(str, Enum):
        A = "a"
        B = "b"

    widget = create_pyqt6_widget(
        "mode",
        Mode | str,
        Mode.A,
        "mode_widget",
    )

    assert isinstance(widget, QComboBox)
    assert widget.count() == 2
    assert widget.itemData(0) is Mode.A


def test_action_tabbed_window_body_switches_active_actions(qapp):
    """Action tab bodies expose only the current tab's actions."""
    from PyQt6.QtWidgets import QLabel, QPushButton
    from pyqt_reactive.widgets.shared.action_tabbed_window_body import (
        ActionTabSpec,
        ActionTabbedWindowBody,
    )

    body = ActionTabbedWindowBody()
    first_actions = QPushButton("first")
    second_actions = QPushButton("second")

    body.add_tab(ActionTabSpec("First", QLabel("first content"), first_actions))
    body.add_tab(ActionTabSpec("Second", QLabel("second content"), second_actions))
    body.show()

    body.set_current_index(0)
    qapp.processEvents()
    assert first_actions.isVisible()
    assert not second_actions.isVisible()

    body.set_current_index(1)
    qapp.processEvents()
    assert not first_actions.isVisible()
    assert second_actions.isVisible()


def test_form_window_action_header_exposes_stable_actions(qapp):
    """Form headers keep title and actions behind stable IDs."""
    from PyQt6.QtWidgets import QPushButton
    from pyqt_reactive.widgets.shared.form_window_action_header import (
        FormWindowActionHeader,
        HeaderAction,
        HeaderActionGroup,
    )

    save_button = QPushButton("Save")
    cancel_button = QPushButton("Cancel")

    header = FormWindowActionHeader(
        title_text="Configure Example",
        action_groups=[
            HeaderActionGroup(
                "save_group",
                [
                    HeaderAction("cancel", cancel_button),
                    HeaderAction("save", save_button),
                ],
            )
        ],
        stay_priority=["save_group"],
        right_aligned_group_ids=["save_group"],
    )

    assert header.header_label.text() == "Configure Example"
    assert header.action("save") is save_button
    assert header.action("cancel") is cancel_button


def test_manager_list_in_place_refresh_skips_unchanged_tooltip(qapp):
    """Unchanged list rows avoid expensive tooltip rebuilds during live refresh."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QListWidget, QListWidgetItem
    from pyqt_reactive.widgets.shared.manager_list_updater import (
        ManagerListUpdateOperations,
        ManagerListUpdater,
    )

    item_obj = {"id": "step-1", "scope": "scope-1"}
    item_list = QListWidget()
    list_item = QListWidgetItem("01: Threshold")
    list_item.setData(Qt.ItemDataRole.UserRole, item_obj)
    list_item.setToolTip("existing tooltip")
    item_list.addItem(list_item)

    tooltip_calls = []
    styled_items = []
    colored_items = []

    operations = ManagerListUpdateOperations(
        item_list=item_list,
        backing_items=[item_obj],
        item_id=lambda item: item["id"],
        should_preserve_selection=lambda: False,
        placeholder=lambda: None,
        prepare_update=lambda: object(),
        clear_scope_cache=lambda: None,
        subscribed_scope_ids=lambda: {"scope-1"},
        scope_for_item=lambda item: item["scope"],
        cleanup_flash_subscriptions=lambda: None,
        clear_scope_to_list_item=lambda: None,
        format_item=lambda item, index, context: "01: Threshold",
        list_item_data_for=lambda item, index: item,
        tooltip_for=lambda item: tooltip_calls.append(item) or "rebuilt tooltip",
        extra_data_for=lambda item, index: {1: "extra-data"},
        set_styling_roles=lambda list_item, display_text, item: styled_items.append(list_item),
        apply_scope_color=lambda list_item, item, index: colored_items.append(list_item),
        subscribe_flash=lambda item, list_item, scope_id: None,
        post_update=lambda: None,
        update_button_states=lambda: None,
    )

    ManagerListUpdater().update(operations)

    refreshed_item = item_list.item(0)
    assert refreshed_item.text() == "01: Threshold"
    assert refreshed_item.toolTip() == "existing tooltip"
    assert tooltip_calls == []
    assert refreshed_item.data(Qt.ItemDataRole.UserRole + 1) == "extra-data"
    assert styled_items == [refreshed_item]
    assert colored_items == [refreshed_item]


def test_restore_selection_by_id_preserves_without_selection_signal(qapp):
    """Programmatic refresh selection does not emit semantic selection changes."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QListWidget, QListWidgetItem
    from pyqt_reactive.widgets.mixins import restore_selection_by_id

    item_list = QListWidget()
    first_item = QListWidgetItem("one")
    first_item.setData(Qt.ItemDataRole.UserRole, {"id": "one"})
    item_list.addItem(first_item)
    item_list.setCurrentRow(0)
    emissions = []
    item_list.itemSelectionChanged.connect(lambda: emissions.append("changed"))

    restore_selection_by_id(
        item_list,
        "one",
        lambda item: item["id"],
    )

    assert item_list.currentRow() == 0
    assert emissions == []

    item_list.clear()
    replacement_item = QListWidgetItem("one")
    replacement_item.setData(Qt.ItemDataRole.UserRole, {"id": "one"})
    item_list.addItem(replacement_item)
    emissions.clear()

    restore_selection_by_id(
        item_list,
        "one",
        lambda item: item["id"],
    )

    assert item_list.currentRow() == 0
    assert emissions == []


def test_visual_update_batch_repaints_after_text_update(qapp):
    """Role-only list updates still need an explicit repaint after batching."""
    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtWidgets import QWidget
    from pyqt_reactive.animation.flash_mixin import VisualUpdateMixin

    class VisualUpdateProbe(QWidget, VisualUpdateMixin):
        def __init__(self):
            super().__init__()
            self.text_updates = 0
            self.repaint_updates = 0
            self._init_visual_update_mixin()

        def _execute_text_update(self) -> None:
            self.text_updates += 1

        def _visual_repaint(self) -> None:
            self.repaint_updates += 1

    widget = VisualUpdateProbe()
    widget.queue_visual_update()

    loop = QEventLoop()
    QTimer.singleShot(40, loop.quit)
    loop.exec()

    assert widget.text_updates == 1
    assert widget.repaint_updates == 1


def test_dispatch_context_skips_empty_root_field_id():
    """Root form managers use empty field ids and must not prefix dotted paths."""
    from types import SimpleNamespace

    from pyqt_reactive.services.field_change_dispatcher import (
        FieldChangeEvent,
        FieldDispatchContextFactory,
    )

    root = SimpleNamespace(field_id="", _parent_manager=None)
    child = SimpleNamespace(
        field_id="well_filter_config",
        _parent_manager=root,
    )

    context = FieldDispatchContextFactory().build(
        FieldChangeEvent("well_filter", "A01", child)
    )

    assert context.source_path == "well_filter_config.well_filter"
    assert context.root_path == "well_filter_config.well_filter"
