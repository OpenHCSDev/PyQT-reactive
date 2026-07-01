"""Tests for extended widgets."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


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


def test_function_form_uses_signature_enums_and_concrete_nested_config(qapp):
    """Function forms derive widgets from signatures and ObjectState path types."""
    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtWidgets import QComboBox
    from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type
    from pyqt_reactive.forms.parameter_form_manager import (
        FormManagerConfig,
        ParameterFormManager,
    )
    from pyqt_reactive.theming import ColorScheme

    class Mode(Enum):
        A = "a"
        B = "b"

    @dataclass
    class BaseConfig:
        output_dir: str = "/tmp"

    class ConfigContract(ABC):
        @property
        @abstractmethod
        def choice(self) -> Mode:
            """Selected mode."""

    @dataclass(frozen=True, slots=True)
    class ConcreteConfig(ConfigContract):
        choice: Mode = Mode.A

    def process(image, mode: Mode | str = Mode.A, config: ConfigContract = ConcreteConfig()):
        return image

    set_base_config_type(BaseConfig)
    ObjectStateRegistry.clear()
    state = ObjectState(
        process,
        scope_id="test::process",
        initial_values={"mode": "b"},
    )
    manager = ParameterFormManager(
        state=state,
        config=FormManagerConfig(
            color_scheme=ColorScheme(),
            function_target=process,
            use_scroll_area=False,
        ),
    )

    try:
        loop = QEventLoop()
        QTimer.singleShot(200, loop.quit)
        loop.exec()

        mode_widget = manager.widgets["mode"]
        assert isinstance(mode_widget, QComboBox)
        assert mode_widget.currentData() is Mode.B

        assert "config" in manager.nested_managers
        nested = manager.nested_managers["config"]
        choice_widget = nested.widgets["choice"]
        assert isinstance(choice_widget, QComboBox)
        assert choice_widget.currentData() is Mode.A
    finally:
        manager.deleteLater()
        ObjectStateRegistry.clear()


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


def test_manager_list_role_update_skips_equal_values(qapp) -> None:
    """Equal role values do not emit QListWidget data updates."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QListWidgetItem
    from pyqt_reactive.widgets.shared.manager_list_updater import ManagerListUpdater

    class CountingItem(QListWidgetItem):
        def __init__(self, text: str):
            super().__init__(text)
            self.set_data_calls = 0

        def setData(self, role, value):
            self.set_data_calls += 1
            return super().setData(role, value)

    item = CountingItem("row")
    item.setData(Qt.ItemDataRole.UserRole, "same")
    item.setData(Qt.ItemDataRole.UserRole + 1, "old")
    item.set_data_calls = 0

    ManagerListUpdater._set_item_data_if_changed(
        item,
        Qt.ItemDataRole.UserRole,
        "same",
    )
    ManagerListUpdater._set_item_data_if_changed(
        item,
        Qt.ItemDataRole.UserRole + 1,
        "new",
    )

    assert item.data(Qt.ItemDataRole.UserRole) == "same"
    assert item.data(Qt.ItemDataRole.UserRole + 1) == "new"
    assert item.set_data_calls == 1


def test_styled_text_size_calculator_caches_layout_metrics(qapp) -> None:
    """Repeated size hints reuse the layout/font metric cache."""
    from PyQt6.QtWidgets import QListWidget
    from pyqt_reactive.widgets.shared.list_item_text_rendering import (
        StyledTextSizeCalculator,
        TextMetricCache,
    )
    from pyqt_reactive.widgets.shared.styled_text_layout import Segment, StyledTextLayout

    metric_cache = TextMetricCache()
    calculator = StyledTextSizeCalculator(metric_cache)
    font = QListWidget().font()
    layout = StyledTextLayout(
        name=Segment("Threshold"),
        preview_segments=[Segment("sigma=1.0"), Segment("mode=otsu")],
        config_segments=[Segment("well_filter=A01")],
        multiline=True,
    )

    first = calculator.from_layout(layout, font)
    size_cache_entries = len(metric_cache._sizes)
    second = calculator.from_layout(layout, font)

    assert second == first
    assert len(metric_cache._sizes) == size_cache_entries


def test_flash_delegate_update_targets_only_item_rect() -> None:
    """Delegate-painted flashes repaint the visible row rect, not the whole viewport."""
    from PyQt6.QtCore import QRect
    from pyqt_reactive.animation.flash_mixin import FlashElement, _GlobalFlashCoordinator

    class Index:
        def isValid(self):
            return True

    class Viewport:
        def __init__(self):
            self.updates = []

        def rect(self):
            return QRect(0, 0, 100, 100)

        def update(self, rect):
            self.updates.append(rect)

    class ListLike:
        def __init__(self):
            self._viewport = Viewport()

        def viewport(self):
            return self._viewport

        def visualRect(self, index):
            return QRect(10, 20, 30, 40)

    widget = ListLike()
    element = FlashElement(
        key="row",
        get_rect_in_window=lambda window: None,
        skip_overlay_paint=True,
        delegate_widget=widget,
        get_model_index=Index,
    )

    _GlobalFlashCoordinator()._update_delegate_element(element)

    assert widget._viewport.updates == [QRect(10, 20, 30, 40)]


def test_widget_service_skips_placeholder_clear_for_concrete_state(qapp):
    """Concrete value updates only clear placeholder chrome when there is state to clear."""
    from types import SimpleNamespace

    from pyqt_reactive.forms.widget_strategies import NoneAwareLineEdit
    from pyqt_reactive.protocols import (
        PlaceholderStateTrackable,
        WidgetCapability,
        widget_supports_capability,
    )
    from pyqt_reactive.services.widget_service import WidgetService

    widget = NoneAwareLineEdit()
    service = WidgetService()
    calls = []

    class FakeEnhancer:
        @staticmethod
        def has_placeholder_state(target):
            assert isinstance(target, PlaceholderStateTrackable)
            assert widget_supports_capability(target, WidgetCapability.PLACEHOLDER_STATE)
            return target.has_placeholder_state()

        def _clear_placeholder_state(self, target):
            calls.append(target)

    service.widget_enhancer = FakeEnhancer()
    manager = SimpleNamespace(field_id="config", object_instance=object())

    service._apply_context_behavior(widget, "abc", "field", manager)

    assert calls == []

    widget.set_cached_placeholder_text("Pipeline default: abc")
    service._apply_context_behavior(widget, "abcd", "field", manager)

    assert calls == [widget]


def test_placeholder_state_methods_declare_generic_capability_tag(qapp):
    """Placeholder-state implementers expose a nominal tag for generic queries."""
    from pyqt_reactive.forms.widget_strategies import NoneAwareLineEdit
    from pyqt_reactive.protocols import (
        PlaceholderStateMixin,
        PlaceholderStateTrackable,
        WidgetCapability,
        widget_capability_tags,
        widget_supports_capability,
    )

    class MethodOnly:
        def has_placeholder_state(self):
            return True

    widget = NoneAwareLineEdit()

    assert WidgetCapability.PLACEHOLDER_STATE in PlaceholderStateTrackable.widget_capabilities
    assert WidgetCapability.PLACEHOLDER_STATE in PlaceholderStateMixin.widget_capabilities
    assert WidgetCapability.PLACEHOLDER_STATE in widget_capability_tags(widget)
    assert widget_supports_capability(widget, WidgetCapability.PLACEHOLDER_STATE)
    assert not widget_supports_capability(MethodOnly(), WidgetCapability.PLACEHOLDER_STATE)


def test_none_aware_line_edit_debounces_text_commits(qapp):
    """Rapid typing commits one semantic value after the user pauses."""
    from PyQt6.QtCore import QEventLoop, QTimer
    from pyqt_reactive.forms.widget_strategies import NoneAwareLineEdit

    widget = NoneAwareLineEdit()
    values = []
    widget.connect_change_signal(values.append)

    widget.setText("a")
    widget.setText("ab")
    widget.setText("abc")

    loop = QEventLoop()
    QTimer.singleShot(180, loop.quit)
    loop.exec()

    assert values == ["abc"]


def test_multiline_delegate_plain_text_fallback_is_quiet(qapp, caplog):
    """List placeholder rows without structured layouts are normal rows."""
    import logging

    from PyQt6.QtCore import QRect, Qt
    from PyQt6.QtGui import QColor, QPainter, QPixmap
    from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QStyle, QStyleOptionViewItem
    from pyqt_reactive.widgets.shared.list_item_delegate import MultilinePreviewItemDelegate

    item_list = QListWidget()
    item = QListWidgetItem("No plate selected - select a plate to view pipeline")
    item_list.addItem(item)
    delegate = MultilinePreviewItemDelegate(
        QColor("black"),
        QColor("gray"),
        QColor("white"),
        parent=item_list,
    )
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 320, 40)
    option.font = item_list.font()
    option.state = QStyle.StateFlag.State_Enabled
    option.widget = item_list
    index = item_list.model().index(0, 0)

    caplog.set_level(logging.WARNING)

    size = delegate.sizeHint(option, index)
    pixmap = QPixmap(340, 60)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        delegate.paint(painter, option, index)
        assert painter.isActive()
    finally:
        painter.end()

    assert size.height() > 0
    assert "sizeHint from text fallback" not in caplog.text
    assert "Expected StyledTextLayout" not in caplog.text


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
