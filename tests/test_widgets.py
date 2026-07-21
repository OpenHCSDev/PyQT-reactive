"""Tests for extended widgets."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class QuotedAnnotationMode(Enum):
    A = "a"
    B = "b"


def process_with_quoted_enum_union(
    image,
    mode: "QuotedAnnotationMode | str" = QuotedAnnotationMode.A,
):
    return image


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


def test_none_aware_checkbox_resolved_preview_dims_lazy_bool(qapp):
    """Generic placeholder previews dim direct lazy-bool checkmarks."""
    from PyQt6.QtGui import QColor, QPalette
    from pyqt_reactive.forms.widget_strategies import PyQt6WidgetEnhancer
    from pyqt_reactive.widgets import NoneAwareCheckBox

    widget = NoneAwareCheckBox()

    PyQt6WidgetEnhancer.apply_placeholder_with_value(
        widget,
        True,
        "Pipeline default: True",
    )

    assert widget.isChecked()
    assert widget.get_value() is None
    assert widget.is_placeholder()
    assert widget.has_placeholder_state()
    assert (
        widget.palette().color(QPalette.ColorRole.WindowText)
        == QColor(136, 136, 136)
    )
    assert widget.cached_placeholder_text() == "Pipeline default: True"
    assert widget.cached_placeholder_resolved_value() is True


def test_none_aware_checkbox_concrete_value_restores_palette(qapp):
    """Leaving placeholder mode restores the checkbox palette."""
    from PyQt6.QtGui import QColor, QPalette
    from pyqt_reactive.widgets import NoneAwareCheckBox

    widget = NoneAwareCheckBox()
    widget.set_placeholder_preview(True)
    assert (
        widget.palette().color(QPalette.ColorRole.WindowText)
        == QColor(136, 136, 136)
    )

    widget.set_value(False)

    assert widget.get_value() is False
    assert not widget.is_placeholder()
    assert (
        widget.palette().color(QPalette.ColorRole.WindowText)
        == qapp.palette().color(QPalette.ColorRole.WindowText)
    )


def test_none_aware_checkbox_resolved_none_previews_unchecked_placeholder(qapp):
    """Resolved None is owned by the checkbox preview contract, not string parsing."""
    from pyqt_reactive.forms.widget_strategies import PyQt6WidgetEnhancer
    from pyqt_reactive.widgets import NoneAwareCheckBox

    widget = NoneAwareCheckBox()

    PyQt6WidgetEnhancer.apply_placeholder_with_value(
        widget,
        None,
        "Pipeline default: None",
    )

    assert not widget.isChecked()
    assert widget.get_value() is None
    assert widget.is_placeholder()
    assert widget.cached_placeholder_resolved_value() is None


def test_none_aware_checkbox_rejects_text_only_placeholder_route(qapp):
    """Typed preview widgets cannot bypass the resolved-value rendering ABI."""
    import pytest
    from pyqt_reactive.forms.widget_strategies import PyQt6WidgetEnhancer
    from pyqt_reactive.widgets import NoneAwareCheckBox

    widget = NoneAwareCheckBox()

    with pytest.raises(TypeError, match="apply_placeholder_with_value"):
        PyQt6WidgetEnhancer.apply_placeholder_text(
            widget,
            "Pipeline default: True",
        )


def test_checkbox_group_resolved_preview_uses_child_preview_contract(qapp):
    """Enum checkbox groups preview inherited membership through the same widget ABI."""
    from enum import Enum
    from PyQt6.QtGui import QColor, QPalette
    from pyqt_reactive.forms.widget_strategies import PyQt6WidgetEnhancer
    from pyqt_reactive.protocols import ResolvedValuePreviewSettable
    from pyqt_reactive.protocols.widget_adapters import CheckboxGroupAdapter
    from pyqt_reactive.widgets import NoneAwareCheckBox

    class Component(Enum):
        SITE = "site"
        CHANNEL = "channel"

    group = CheckboxGroupAdapter()
    for enum_value in Component:
        checkbox = NoneAwareCheckBox()
        checkbox.setText(enum_value.value)
        group._checkboxes[enum_value] = checkbox

    assert isinstance(group, ResolvedValuePreviewSettable)

    PyQt6WidgetEnhancer.apply_placeholder_with_value(
        group,
        [Component.SITE],
        "Pipeline default: [site]",
    )

    site = group._checkboxes[Component.SITE]
    channel = group._checkboxes[Component.CHANNEL]
    assert site.isChecked()
    assert not channel.isChecked()
    assert site.get_value() is None
    assert channel.get_value() is None
    assert site.is_placeholder()
    assert channel.is_placeholder()
    assert group.get_value() is None
    assert group.has_placeholder_state()
    assert group.cached_placeholder_resolved_value() == [Component.SITE]
    assert (
        site.palette().color(QPalette.ColorRole.WindowText)
        == QColor(136, 136, 136)
    )


def test_enableable_dimming_defers_to_placeholder_state_contract(qapp):
    """Enableable dimming does not double-dim widgets that own placeholder paint."""
    from enum import Enum
    from pyqt_reactive.protocols import PlaceholderStateTrackable
    from pyqt_reactive.protocols.widget_adapters import CheckboxGroupAdapter
    from pyqt_reactive.services.enabled_field_styling_service import (
        EnabledFieldStylingService,
    )
    from pyqt_reactive.widgets import NoneAwareCheckBox

    class Component(Enum):
        SITE = "site"

    service = EnabledFieldStylingService()

    checkbox = NoneAwareCheckBox()
    checkbox.set_value(True)
    assert isinstance(checkbox, PlaceholderStateTrackable)
    assert service._set_widget_dimmed(checkbox, True)
    assert checkbox.graphicsEffect() is not None
    checkbox.set_resolved_value_preview(True)
    assert service._set_widget_dimmed(checkbox, True)
    assert checkbox.graphicsEffect() is None
    assert checkbox.property("enabled_field_dimmed") is False
    assert service._set_widget_dimmed(
        checkbox,
        True,
        preserve_placeholder_paint=False,
    )
    assert checkbox.graphicsEffect() is not None
    assert checkbox.property("enabled_field_dimmed") is True

    group = CheckboxGroupAdapter()
    group_checkbox = NoneAwareCheckBox()
    group._checkboxes[Component.SITE] = group_checkbox
    group.set_value([Component.SITE])
    assert isinstance(group, PlaceholderStateTrackable)
    assert service._set_widget_dimmed(group, True)
    assert group.graphicsEffect() is not None
    group.set_resolved_value_preview([Component.SITE])
    assert service._set_widget_dimmed(group, True)
    assert group.graphicsEffect() is None
    assert group.property("enabled_field_dimmed") is False


def test_checkbox_group_creation_preserves_single_enum_list_value(qapp):
    """List[Enum] widget creation must not unwrap one selected value to a scalar."""
    from enum import Enum
    from pyqt_reactive.forms.widget_strategies import create_pyqt6_widget
    from pyqt_reactive.protocols.widget_adapters import CheckboxGroupAdapter

    class Component(Enum):
        SITE = "site"
        CHANNEL = "channel"

    widget = create_pyqt6_widget(
        "variable_components",
        list[Component],
        [Component.SITE],
        "variable_components",
    )

    assert isinstance(widget, CheckboxGroupAdapter)
    assert widget.get_value() == [Component.SITE]
    assert widget.checkbox_items()[0][1].get_value() is True


def test_placeholder_refresh_preserves_concrete_checkbox_group_default(qapp):
    """Concrete list defaults must not be repainted as inherited placeholders."""
    from enum import Enum
    from types import SimpleNamespace
    from pyqt_reactive.forms.widget_strategies import create_pyqt6_widget
    from pyqt_reactive.services.parameter_ops_service import ParameterOpsService

    class Component(Enum):
        SITE = "site"
        CHANNEL = "channel"

    widget = create_pyqt6_widget(
        "variable_components",
        list[Component],
        [Component.SITE],
        "variable_components",
    )
    service = ParameterOpsService()
    manager = SimpleNamespace(
        field_id="processing_config",
        object_instance=object(),
        widgets={"variable_components": widget},
        parameters={"variable_components": [Component.SITE]},
        config=SimpleNamespace(placeholder_prefix="Default"),
        state=SimpleNamespace(
            get_resolved_value=lambda path: [Component.SITE],
        ),
    )

    service.refresh_all_placeholders(manager)

    assert widget.get_value() == [Component.SITE]
    assert not widget.has_placeholder_state()
    for _, checkbox in widget.checkbox_items():
        assert not checkbox.is_placeholder()


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


def test_editable_function_pattern_resolves_quoted_enum_annotations(qapp):
    """Editable function-pattern wrappers preserve resolved enum widget types."""
    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtWidgets import QComboBox
    from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type
    from pyqt_reactive.forms.parameter_form_manager import (
        FormManagerConfig,
        ParameterFormManager,
    )
    from pyqt_reactive.services.function_pattern_code_document import (
        EditableFunctionPatternCallable,
    )
    from pyqt_reactive.theming import ColorScheme

    editable = EditableFunctionPatternCallable.for_entry(
        process_with_quoted_enum_union,
        {"extra_setting": "value"},
    )

    @dataclass
    class BaseConfig:
        output_dir: str = "/tmp"

    set_base_config_type(BaseConfig)
    ObjectStateRegistry.clear()
    state = ObjectState(
        editable,
        scope_id="test::editable_quoted_enum",
        initial_values={"mode": QuotedAnnotationMode.B, "extra_setting": "value"},
    )
    manager = ParameterFormManager(
        state=state,
        config=FormManagerConfig(
            color_scheme=ColorScheme(),
            function_target=editable,
            use_scroll_area=False,
        ),
    )

    try:
        loop = QEventLoop()
        QTimer.singleShot(200, loop.quit)
        loop.exec()

        mode_widget = manager.widgets["mode"]
        assert isinstance(mode_widget, QComboBox)
        assert mode_widget.currentData() is QuotedAnnotationMode.B
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


def test_action_tabbed_window_body_shows_tabs_only_for_multiple_pages(qapp):
    """A single page renders without tab chrome; a second page enables it."""
    from PyQt6.QtWidgets import QLabel
    from pyqt_reactive.widgets.shared.action_tabbed_window_body import (
        ActionTabSpec,
        ActionTabbedWindowBody,
    )

    body = ActionTabbedWindowBody()
    first_content = QLabel("first content")
    body.add_tab(ActionTabSpec("First", first_content))

    assert body.tab_bar.isHidden()
    assert body.current_widget() is first_content

    body.add_tab(ActionTabSpec("Second", QLabel("second content")))

    assert not body.tab_bar.isHidden()


def test_responsive_parameter_row_wraps_only_below_minimum_capacity(qapp):
    """Parameter rows use all available width without an empty editor column."""
    from PyQt6.QtWidgets import QLabel, QLineEdit, QPushButton
    from pyqt_reactive.widgets.shared.responsive_layout_widgets import (
        ResponsiveParameterRow,
        ResponsiveRowLayoutMode,
    )

    row = ResponsiveParameterRow()
    label = QLabel("Descriptor Directory Path:")
    editor = QLineEdit("/tmp/pipeline-default")
    reset = QPushButton("Reset")
    row.set_label(label)
    row.set_input(editor)
    row.set_reset_button(reset)
    row.show()

    required_width = row._calculate_content_width()
    row.resize(required_width, row.sizeHint().height())
    qapp.processEvents()
    row._check_switch()
    qapp.processEvents()

    assert row._layout_mode is ResponsiveRowLayoutMode.HORIZONTAL
    assert row._row1_layout.count() == 3
    assert row._row1_layout.itemAt(0).widget() is label
    assert row._row1_layout.itemAt(1).widget() is editor
    assert row._row1_layout.itemAt(2).widget() is reset
    assert editor.geometry().left() <= label.geometry().right() + row._row1_layout.spacing() + 1
    assert reset.geometry().right() >= row.contentsRect().right() - row._row1_layout.contentsMargins().right() - 1

    row.resize(required_width - 1, row.sizeHint().height() * 2)
    row._check_switch()
    qapp.processEvents()

    assert row._layout_mode is ResponsiveRowLayoutMode.VERTICAL
    assert row._row2_layout.count() == 2
    assert row._row2_layout.itemAt(0).widget() is editor
    assert row._row2_layout.itemAt(1).widget() is reset
    assert editor.geometry().left() <= row._row2_layout.contentsMargins().left() + 1
    assert reset.geometry().right() >= row.contentsRect().right() - row._row2_layout.contentsMargins().right() - 1


def test_action_tab_row_keeps_tabs_and_actions_on_one_row_when_they_fit(qapp):
    """Top-level tabs and active actions wrap only under horizontal pressure."""
    from PyQt6.QtWidgets import QLabel, QPushButton
    from pyqt_reactive.widgets.shared.action_tabbed_window_body import (
        ActionTabSpec,
        ActionTabbedWindowBody,
    )
    from pyqt_reactive.widgets.shared.responsive_layout_widgets import (
        ResponsiveRowLayoutMode,
    )

    body = ActionTabbedWindowBody()
    actions = QPushButton("Reset  View Code  Help")
    body.add_tab(ActionTabSpec("Pipeline", QLabel("content"), actions))
    body.add_tab(ActionTabSpec("UI", QLabel("ui content")))
    body.show()

    required_width = body.tab_row._calculate_content_width()
    body.resize(required_width, 240)
    qapp.processEvents()
    body.tab_row._check_switch()
    qapp.processEvents()

    assert body.tab_row._layout_mode is ResponsiveRowLayoutMode.HORIZONTAL
    assert body.tab_row._row1_layout.count() == 3
    assert body.tab_row._row1_layout.itemAt(0).widget() is body.tab_bar
    assert body.tab_row._row1_layout.itemAt(1).spacerItem() is not None
    assert body.tab_row._row1_layout.itemAt(2).widget() is body._active_actions_container
    assert body._active_actions_container.geometry().right() >= body.tab_row.contentsRect().right() - 1

    body.resize(required_width - 1, 240)
    body.tab_row._check_switch()
    qapp.processEvents()

    assert body.tab_row._layout_mode is ResponsiveRowLayoutMode.VERTICAL
    assert body.tab_row._row2_layout.count() == 2
    assert body.tab_row._row2_layout.itemAt(0).spacerItem() is not None
    assert body.tab_row._row2_layout.itemAt(1).widget() is body._active_actions_container
    assert body._active_actions_container.geometry().right() >= body.tab_row.contentsRect().right() - 1


def test_action_tab_border_uses_top_level_foreground_color(qapp):
    """Direct config tabs use the same visible foreground border on every tab."""
    from pyqt_reactive.theming.color_scheme import ColorScheme
    from pyqt_reactive.widgets.shared.action_tabbed_window_body import (
        ActionTabbedWindowBody,
    )

    color_scheme = ColorScheme()
    body = ActionTabbedWindowBody(color_scheme=color_scheme)

    assert (
        f"border: 1px solid {color_scheme.to_hex(color_scheme.text_primary)};"
        in body.tab_bar.styleSheet()
    )


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


def test_form_window_action_header_places_semantic_groups_by_capacity(qapp):
    """Semantic groups stay attached to their declared header regions."""
    from PyQt6.QtCore import QRect, Qt
    from PyQt6.QtWidgets import QPushButton

    from pyqt_reactive.widgets.shared.form_window_action_header import (
        FormWindowActionHeader,
        HeaderAction,
        HeaderActionGroup,
        HeaderActionGroupRole,
    )
    from pyqt_reactive.widgets.shared.responsive_layout_widgets import (
        _widget_required_width,
    )

    buttons = {
        label: QPushButton(label)
        for label in ("Cancel", "Save", "Reset", "View Code", "Help")
    }
    header = FormWindowActionHeader(
        title_text="Config PipelineConfig",
        action_groups=[
            HeaderActionGroup(
                "help",
                [HeaderAction("help", buttons["Help"])],
                role=HeaderActionGroupRole.TITLE_COMPANION,
            ),
            HeaderActionGroup(
                "auxiliary",
                [
                    HeaderAction("reset", buttons["Reset"]),
                    HeaderAction("view_code", buttons["View Code"]),
                ],
                role=HeaderActionGroupRole.AUXILIARY,
            ),
            HeaderActionGroup(
                "commit",
                [
                    HeaderAction("cancel", buttons["Cancel"]),
                    HeaderAction("save", buttons["Save"]),
                ],
                role=HeaderActionGroupRole.COMMIT,
            ),
        ],
    )
    layout = header._layout_widget
    header.show()

    widths = {
        name: _widget_required_width(widget)
        for name, widget in layout._groups
    }
    required_width = layout._row_width(["title", "auxiliary", "commit"], widths)
    header.resize(required_width, header.sizeHint().height())
    qapp.processEvents()
    layout._update_layout()
    qapp.processEvents()

    assert layout._last_row1 == ["title", "auxiliary", "commit"]
    assert layout._last_row2 == []
    assert header.header_label.wordWrap()
    text_flags = int(
        Qt.AlignmentFlag.AlignLeft.value | Qt.TextFlag.TextWordWrap.value
    )
    text_rect = header.header_label.fontMetrics().boundingRect(
        QRect(0, 0, header.header_label.width(), 10_000),
        text_flags,
        header.header_label.text(),
    )
    one_line_text_height = header.header_label.fontMetrics().boundingRect(
        QRect(0, 0, 10_000, 10_000),
        text_flags,
        header.header_label.text(),
    ).height()
    assert text_rect.height() == one_line_text_height, (
        widths,
        required_width,
        header.width(),
        layout.width(),
        [(name, widget.geometry().getRect()) for name, widget in layout._groups],
        header.header_label.geometry().getRect(),
    )
    assert header.header_label.width() >= header.header_label.fontMetrics().horizontalAdvance(
        header.header_label.text()
    )
    title_group = dict(layout._groups)["title"]
    commit_group = dict(layout._groups)["commit"]
    assert buttons["Help"].parentWidget() is title_group
    assert header.header_label.geometry().right() < buttons["Help"].geometry().left()
    assert commit_group.geometry().right() >= layout.contentsRect().right() - 1

    header.resize(required_width - 1, header.sizeHint().height() * 2)
    layout._update_layout()
    qapp.processEvents()

    assert layout._last_row1 == ["title", "commit"]
    assert layout._last_row2 == ["auxiliary"]
    assert commit_group.geometry().right() >= layout.contentsRect().right() - 1
    auxiliary_group = dict(layout._groups)["auxiliary"]
    assert auxiliary_group.geometry().right() >= layout.contentsRect().right() - 1


def test_form_window_action_header_contains_wrapped_title_and_restores_wide_layout(qapp):
    """Genuine pressure wraps the title without clipping or stale row geometry."""
    from PyQt6.QtCore import QRect, Qt
    from PyQt6.QtWidgets import QPushButton

    from pyqt_reactive.widgets.shared.form_window_action_header import (
        FormWindowActionHeader,
        HeaderAction,
        HeaderActionGroup,
        HeaderActionGroupRole,
    )
    from pyqt_reactive.widgets.shared.responsive_layout_widgets import (
        _widget_required_width,
    )

    help_button = QPushButton("Help")
    reset_button = QPushButton("Reset")
    commit_button = QPushButton("Cancel and Save")
    header = FormWindowActionHeader(
        title_text="Config PipelineConfigurationWithLongName",
        action_groups=[
            HeaderActionGroup(
                "help",
                [HeaderAction("help", help_button)],
                role=HeaderActionGroupRole.TITLE_COMPANION,
            ),
            HeaderActionGroup(
                "auxiliary",
                [HeaderAction("reset", reset_button)],
                role=HeaderActionGroupRole.AUXILIARY,
            ),
            HeaderActionGroup(
                "commit",
                [HeaderAction("commit", commit_button)],
                role=HeaderActionGroupRole.COMMIT,
            ),
        ],
    )
    layout = header._layout_widget
    header.show()
    qapp.processEvents()

    widths = {
        name: _widget_required_width(widget)
        for name, widget in layout._groups
    }
    wide_width = layout._row_width(["title", "auxiliary", "commit"], widths)
    header.resize(wide_width, header.sizeHint().height())
    layout._update_layout()
    qapp.processEvents()
    header.resize(wide_width, header.sizeHint().height())
    qapp.processEvents()

    assert layout._last_row1 == ["title", "auxiliary", "commit"]
    assert layout._last_row2 == []
    text_flags = int(
        Qt.AlignmentFlag.AlignLeft.value | Qt.TextFlag.TextWordWrap.value
    )
    wide_text_rect = header.header_label.fontMetrics().boundingRect(
        QRect(0, 0, header.header_label.width(), 10_000),
        text_flags,
        header.header_label.text(),
    )
    one_line_text_height = header.header_label.fontMetrics().boundingRect(
        QRect(0, 0, 10_000, 10_000),
        text_flags,
        header.header_label.text(),
    ).height()
    assert wide_text_rect.height() == one_line_text_height

    reset_button.setVisible(False)
    header.refresh_layout()
    compact_width = max(
        widths["commit"],
        help_button.sizeHint().width()
        + header.header_label.minimumSizeHint().width()
        + layout._spacing,
    )
    header.resize(compact_width, header.sizeHint().height() * 3)
    layout._update_layout()
    qapp.processEvents()
    header.resize(compact_width, header.sizeHint().height())
    qapp.processEvents()

    assert layout._last_row1 == ["auxiliary", "commit"]
    assert layout._last_row2 == ["title"]
    compact_text_rect = header.header_label.fontMetrics().boundingRect(
        QRect(0, 0, header.header_label.width(), 10_000),
        text_flags,
        header.header_label.text(),
    )
    assert compact_text_rect.height() > one_line_text_height
    assert compact_text_rect.height() <= header.header_label.contentsRect().height()
    title_group = dict(layout._groups)["title"]
    assert header.header_label.geometry().bottom() <= title_group.contentsRect().bottom()
    assert title_group.mapTo(header, title_group.rect().bottomLeft()).y() <= (
        header.contentsRect().bottom()
    )

    reset_button.setVisible(True)
    header.resize(wide_width, header.height())
    header.refresh_layout()
    qapp.processEvents()
    header.resize(wide_width, header.sizeHint().height())
    qapp.processEvents()

    assert layout._last_row1 == ["title", "auxiliary", "commit"]
    assert layout._last_row2 == []
    assert header.height() == layout.heightForWidth(wide_width)
    restored_text_rect = header.header_label.fontMetrics().boundingRect(
        QRect(0, 0, header.header_label.width(), 10_000),
        text_flags,
        header.header_label.text(),
    )
    assert restored_text_rect.height() == one_line_text_height


def test_groupbox_title_keeps_reset_all_on_one_row_at_capacity(qapp):
    """Dataclass titles wrap their explicit Reset All action only under pressure."""
    from PyQt6.QtWidgets import QPushButton
    from pyqt_reactive.widgets.shared.clickable_help_components import (
        GroupBoxWithHelp,
    )

    groupbox = GroupBoxWithHelp(title="Source Bindings Config")
    reset_all = QPushButton("Reset All")
    groupbox.addResetAllTitleWidget(reset_all)
    title = groupbox.title_layout
    groupbox.show()

    widths = {
        name: widget.minimumSizeHint().width()
        for name, widget in title._staged_layout._groups
    }
    required_width = title._staged_layout._row_width(
        [title.TITLE_GROUP, title.INLINE_GROUP, title.RIGHT_GROUP],
        widths,
    )
    outer_width = groupbox.width() - title._staged_layout.width()
    groupbox.resize(required_width + outer_width, groupbox.sizeHint().height())
    qapp.processEvents()
    title._staged_layout._update_layout()
    qapp.processEvents()

    assert title._staged_layout._last_row1 == [
        title.TITLE_GROUP,
        title.INLINE_GROUP,
        title.RIGHT_GROUP,
    ]
    assert title._staged_layout._last_row2 == []
    right_group = dict(title._staged_layout._groups)[title.RIGHT_GROUP]
    assert (
        right_group.geometry().right()
        >= title._staged_layout.contentsRect().right() - 1
    )

    groupbox.resize(
        required_width + outer_width - 1,
        groupbox.sizeHint().height() * 2,
    )
    title._staged_layout._update_layout()
    qapp.processEvents()

    assert title._staged_layout._last_row1 == [
        title.TITLE_GROUP,
        title.INLINE_GROUP,
    ]
    assert title._staged_layout._last_row2 == [title.RIGHT_GROUP]
    assert (
        right_group.geometry().right()
        >= title._staged_layout.contentsRect().right() - 1
    )


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
        should_refresh_text_for_scope_change=lambda item, changed_paths: True,
        list_item_data_for=lambda item, index: item,
        tooltip_for=lambda item: tooltip_calls.append(item) or "rebuilt tooltip",
        extra_data_for=lambda item, index: {1: "extra-data"},
        set_styling_roles=lambda list_item, display_text, item: styled_items.append(list_item),
        refresh_styling_roles=lambda list_item, item: None,
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


def test_manager_list_scope_refresh_updates_only_matching_rows(qapp):
    """ObjectState row refreshes avoid full-list formatting work."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QListWidget, QListWidgetItem
    from pyqt_reactive.widgets.shared.manager_list_updater import (
        ManagerListUpdateOperations,
        ManagerListUpdater,
    )

    items = [
        {"id": "step-1", "scope": "scope-1"},
        {"id": "step-2", "scope": "scope-2"},
        {"id": "step-3", "scope": "scope-3"},
    ]
    item_list = QListWidget()
    for index, item in enumerate(items):
        list_item = QListWidgetItem(f"old-{index}")
        list_item.setData(Qt.ItemDataRole.UserRole, item)
        item_list.addItem(list_item)

    formatted_scopes = []
    operations = ManagerListUpdateOperations(
        item_list=item_list,
        backing_items=items,
        item_id=lambda item: item["id"],
        should_preserve_selection=lambda: False,
        placeholder=lambda: None,
        prepare_update=lambda: object(),
        clear_scope_cache=lambda: None,
        subscribed_scope_ids=lambda: {"scope-1", "scope-2", "scope-3"},
        scope_for_item=lambda item: item["scope"],
        cleanup_flash_subscriptions=lambda: None,
        clear_scope_to_list_item=lambda: None,
        format_item=lambda item, index, context: (
            formatted_scopes.append(item["scope"]) or f"new-{index}"
        ),
        should_refresh_text_for_scope_change=lambda item, changed_paths: True,
        list_item_data_for=lambda item, index: item,
        tooltip_for=lambda item: "tooltip",
        extra_data_for=lambda item, index: {},
        set_styling_roles=lambda list_item, display_text, item: None,
        refresh_styling_roles=lambda list_item, item: None,
        apply_scope_color=lambda list_item, item, index: None,
        subscribe_flash=lambda item, list_item, scope_id: None,
        post_update=lambda: None,
        update_button_states=lambda: None,
    )

    refreshed = ManagerListUpdater().refresh_scopes(operations, {"scope-2"})

    assert refreshed is True
    assert formatted_scopes == ["scope-2"]
    assert item_list.item(0).text() == "old-0"
    assert item_list.item(1).text() == "new-1"
    assert item_list.item(2).text() == "old-2"


def test_manager_list_in_place_refresh_does_not_infer_flash_from_text(qapp):
    """Rendered text changes are not semantic flash events by themselves."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QListWidget, QListWidgetItem
    from pyqt_reactive.widgets.shared.manager_list_updater import (
        ManagerListUpdateOperations,
        ManagerListUpdater,
    )

    item_obj = {"id": "step-1", "scope": "scope-1"}
    item_list = QListWidget()
    list_item = QListWidgetItem("01: Old preview")
    list_item.setData(Qt.ItemDataRole.UserRole, item_obj)
    item_list.addItem(list_item)
    flash_calls = []

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
        format_item=lambda item, index, context: "01: New preview",
        should_refresh_text_for_scope_change=lambda item, changed_paths: True,
        list_item_data_for=lambda item, index: item,
        tooltip_for=lambda item: "new tooltip",
        extra_data_for=lambda item, index: {},
        set_styling_roles=lambda list_item, display_text, item: None,
        refresh_styling_roles=lambda list_item, item: None,
        apply_scope_color=lambda list_item, item, index: None,
        subscribe_flash=lambda item, list_item, scope_id: None,
        post_update=lambda: None,
        update_button_states=lambda: None,
    )

    ManagerListUpdater().update(operations)

    assert item_list.item(0).text() == "01: New preview"
    assert flash_calls == []


def test_manager_list_rebuild_does_not_infer_flash_from_new_scope(qapp):
    """Row materialization is view state, not an ObjectState value change."""
    from PyQt6.QtWidgets import QListWidget
    from pyqt_reactive.widgets.shared.manager_list_updater import (
        ManagerListUpdateOperations,
        ManagerListUpdater,
    )

    item_obj = {"id": "step-1", "scope": "scope-1"}
    item_list = QListWidget()
    subscribed = set()
    subscribed_order = []
    flash_calls = []

    operations = ManagerListUpdateOperations(
        item_list=item_list,
        backing_items=[item_obj],
        item_id=lambda item: item["id"],
        should_preserve_selection=lambda: False,
        placeholder=lambda: None,
        prepare_update=lambda: object(),
        clear_scope_cache=lambda: None,
        subscribed_scope_ids=lambda: set(subscribed),
        scope_for_item=lambda item: item["scope"],
        cleanup_flash_subscriptions=lambda: subscribed.clear(),
        clear_scope_to_list_item=lambda: None,
        format_item=lambda item, index, context: "01: New row",
        should_refresh_text_for_scope_change=lambda item, changed_paths: True,
        list_item_data_for=lambda item, index: item,
        tooltip_for=lambda item: "new tooltip",
        extra_data_for=lambda item, index: {},
        set_styling_roles=lambda list_item, display_text, item: None,
        refresh_styling_roles=lambda list_item, item: None,
        apply_scope_color=lambda list_item, item, index: None,
        subscribe_flash=lambda item, list_item, scope_id: (
            subscribed.add(scope_id),
            subscribed_order.append(scope_id),
        ),
        post_update=lambda: None,
        update_button_states=lambda: None,
    )

    ManagerListUpdater().update(operations)

    assert item_list.item(0).text() == "01: New row"
    assert subscribed_order == ["scope-1"]
    assert flash_calls == []


def test_manager_list_rebuild_does_not_flash_existing_scope(qapp):
    """Rebuilds caused by deletion do not flash scopes that already existed."""
    from PyQt6.QtWidgets import QListWidget, QListWidgetItem
    from pyqt_reactive.widgets.shared.manager_list_updater import (
        ManagerListUpdateOperations,
        ManagerListUpdater,
    )

    item_obj = {"id": "step-1", "scope": "scope-1"}
    item_list = QListWidget()
    item_list.addItem(QListWidgetItem("old surviving row"))
    item_list.addItem(QListWidgetItem("removed row"))
    subscribed = {"scope-1", "scope-2"}

    operations = ManagerListUpdateOperations(
        item_list=item_list,
        backing_items=[item_obj],
        item_id=lambda item: item["id"],
        should_preserve_selection=lambda: False,
        placeholder=lambda: None,
        prepare_update=lambda: object(),
        clear_scope_cache=lambda: None,
        subscribed_scope_ids=lambda: set(subscribed),
        scope_for_item=lambda item: item["scope"],
        cleanup_flash_subscriptions=lambda: subscribed.clear(),
        clear_scope_to_list_item=lambda: None,
        format_item=lambda item, index, context: "01: Surviving row",
        should_refresh_text_for_scope_change=lambda item, changed_paths: True,
        list_item_data_for=lambda item, index: item,
        tooltip_for=lambda item: "new tooltip",
        extra_data_for=lambda item, index: {},
        set_styling_roles=lambda list_item, display_text, item: None,
        refresh_styling_roles=lambda list_item, item: None,
        apply_scope_color=lambda list_item, item, index: None,
        subscribe_flash=lambda item, list_item, scope_id: subscribed.add(scope_id),
        post_update=lambda: None,
        update_button_states=lambda: None,
    )

    ManagerListUpdater().update(operations)

    assert item_list.count() == 1
    assert item_list.item(0).text() == "01: Surviving row"


def test_manager_list_visual_state_flashes_visible_objectstate_change(qapp):
    """Visible list rows flash from ObjectState resolved-change authority."""
    from dataclasses import dataclass
    from PyQt6.QtWidgets import QDialog, QListWidget, QListWidgetItem
    from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type
    from pyqt_reactive.animation import WindowFlashOverlay
    from pyqt_reactive.widgets.shared.manager_list_visual_state import (
        ManagerListVisualState,
    )

    @dataclass
    class RowState:
        value: int = 1

    @dataclass
    class BaseConfig:
        value: int = 0

    class ItemAccess:
        def scope_for_item(self, item):
            return item["scope"]

    class Manager(QDialog):
        def __init__(self):
            super().__init__()
            self.item_list = QListWidget(self)
            self.queued_flashes = []
            self.visual_scope_updates = set()

        def queue_flash_batch(self, scope_ids):
            self.queued_flashes.extend(scope_ids)

        def queue_list_scope_visual_update(self, scope_id, changed_paths=None):
            self.visual_scope_updates.add(scope_id)

    set_base_config_type(BaseConfig)
    ObjectStateRegistry.clear()
    state = ObjectState(RowState(), scope_id="scope-1")
    ObjectStateRegistry.register(state, _skip_snapshot=True)
    manager = Manager()
    visual_state = ManagerListVisualState(manager, 99, ItemAccess())
    list_item = QListWidgetItem("row")
    manager.item_list.addItem(list_item)

    try:
        visual_state.subscribe_flash({"scope": "scope-1"}, list_item, "scope-1")
        overlay = WindowFlashOverlay.get_for_window(manager)

        assert overlay is not None
        assert any(
            element.hierarchical_key_prefix
            for element in overlay._elements["scope-1"]
        )

        state.update_object_instance(RowState(value=2))
        qapp.processEvents()

        assert "scope-1" in manager.queued_flashes
        assert manager.visual_scope_updates == {"scope-1"}
    finally:
        visual_state.dispose()
        WindowFlashOverlay.cleanup_window(manager)
        manager.deleteLater()
        ObjectStateRegistry.clear()


def test_manager_list_visual_state_buffers_objectstate_change_until_row_visible(qapp):
    """Resolved changes that precede row materialization flash once on subscribe."""
    from dataclasses import dataclass
    from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QWidget
    from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type
    from pyqt_reactive.widgets.shared.manager_list_visual_state import (
        ManagerListVisualState,
    )

    @dataclass
    class RowState:
        value: int = 1

    @dataclass
    class BaseConfig:
        value: int = 0

    class ItemAccess:
        def scope_for_item(self, item):
            return item["scope"]

    class Manager(QWidget):
        def __init__(self):
            super().__init__()
            self.item_list = QListWidget(self)
            self.queued_flashes = []

        def queue_flash_batch(self, scope_ids):
            self.queued_flashes.extend(scope_ids)

        def queue_list_scope_visual_update(self, scope_id, changed_paths=None):
            pass

    set_base_config_type(BaseConfig)
    ObjectStateRegistry.clear()
    state = ObjectState(RowState(), scope_id="scope-1")
    ObjectStateRegistry.register(state, _skip_snapshot=True)
    manager = Manager()
    visual_state = ManagerListVisualState(manager, 99, ItemAccess())

    try:
        state.update_object_instance(RowState(value=2))

        assert manager.queued_flashes == []

        list_item = QListWidgetItem("row")
        manager.item_list.addItem(list_item)
        visual_state.subscribe_flash({"scope": "scope-1"}, list_item, "scope-1")

        assert manager.queued_flashes == ["scope-1"]
    finally:
        visual_state.dispose()
        manager.deleteLater()
        ObjectStateRegistry.clear()


def test_manager_list_visual_state_reset_context_discards_pending_flash(qapp):
    """Explicit list-context resets do not replay stale ObjectState flashes."""
    from dataclasses import dataclass
    from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QWidget
    from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type
    from pyqt_reactive.widgets.shared.manager_list_visual_state import (
        ManagerListVisualState,
    )

    @dataclass
    class RowState:
        value: int = 1

    @dataclass
    class BaseConfig:
        value: int = 0

    class ItemAccess:
        def scope_for_item(self, item):
            return item["scope"]

    class Manager(QWidget):
        def __init__(self):
            super().__init__()
            self.item_list = QListWidget(self)
            self.queued_flashes = []

        def queue_flash_batch(self, scope_ids):
            self.queued_flashes.extend(scope_ids)

        def queue_list_scope_visual_update(self, scope_id, changed_paths=None):
            pass

    set_base_config_type(BaseConfig)
    ObjectStateRegistry.clear()
    state = ObjectState(RowState(), scope_id="scope-1")
    ObjectStateRegistry.register(state, _skip_snapshot=True)
    manager = Manager()
    visual_state = ManagerListVisualState(manager, 99, ItemAccess())

    try:
        state.update_object_instance(RowState(value=2))
        visual_state.reset_context()

        list_item = QListWidgetItem("row")
        manager.item_list.addItem(list_item)
        visual_state.subscribe_flash({"scope": "scope-1"}, list_item, "scope-1")

        assert manager.queued_flashes == []
    finally:
        visual_state.dispose()
        manager.deleteLater()
        ObjectStateRegistry.clear()


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


def test_delegate_flash_tracks_descendant_objectstate_key() -> None:
    """Delegate-painted rows repaint from descendant ObjectState flash paths."""
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QColor
    from pyqt_reactive.animation.flash_mixin import (
        FlashElement,
        _GlobalFlashCoordinator,
        create_list_item_element,
    )

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

    class TreeLike:
        def __init__(self):
            self._viewport = Viewport()

        def viewport(self):
            return self._viewport

        def visualRect(self, index):
            return QRect(10, 20, 30, 40)

    delegate_view = TreeLike()
    ancestor_key = "scope::source_bindings"
    descendant_key = "scope::source_bindings.source_filters"
    ancestor_element = FlashElement(
        key=ancestor_key,
        get_rect_in_window=lambda window: None,
        source_id="delegate:source_bindings",
        skip_overlay_paint=True,
        hierarchical_key_prefix=True,
        delegate_widget=delegate_view,
        get_model_index=Index,
    )
    overlay = type(
        "Overlay",
        (),
        {
            "_elements": {
                ancestor_key: [ancestor_element],
            },
            "_hierarchical_delegate_keys": {ancestor_key},
        },
    )()
    coordinator = _GlobalFlashCoordinator()
    descendant_color = QColor(10, 20, 30, 120)
    coordinator._computed_colors[descendant_key] = descendant_color

    overlay_keys = coordinator._overlay_flash_keys(overlay, {descendant_key})
    needs_overlay_paint = coordinator._update_overlay_for_keys(overlay, overlay_keys)

    assert needs_overlay_paint is False
    assert delegate_view._viewport.updates == [QRect(10, 20, 30, 40)]
    assert (
        coordinator.get_computed_color_for_object_state_path(ancestor_key)
        == descendant_color
    )
    assert overlay_keys == {ancestor_key}

    exact_leaf_element = FlashElement(
        key=descendant_key,
        get_rect_in_window=lambda window: QRect(0, 0, 10, 10),
        source_id="field:source_filters",
    )
    overlay_with_exact_leaf = type(
        "Overlay",
        (),
        {
            "_elements": {
                ancestor_key: [ancestor_element],
                descendant_key: [exact_leaf_element],
            },
            "_hierarchical_delegate_keys": {ancestor_key},
        },
    )()
    delegate_view._viewport.updates.clear()

    overlay_keys = coordinator._overlay_flash_keys(
        overlay_with_exact_leaf,
        {descendant_key},
    )
    needs_overlay_paint = coordinator._update_overlay_for_keys(
        overlay_with_exact_leaf,
        overlay_keys,
    )

    assert overlay_keys == {ancestor_key, descendant_key}
    assert needs_overlay_paint is True
    assert delegate_view._viewport.updates == [QRect(10, 20, 30, 40)]

    list_element = create_list_item_element(
        ancestor_key,
        type(
            "ListWidget",
            (),
            {
                "item": lambda self, row: object(),
                "isVisible": lambda self: True,
                "isVisibleTo": lambda self, window: True,
                "visualItemRect": lambda self, item: QRect(0, 0, 10, 10),
                "viewport": lambda self: delegate_view.viewport(),
                "indexFromItem": lambda self, item: Index(),
            },
        )(),
        lambda: 0,
    )
    assert list_element.hierarchical_key_prefix is True

    scope_row_key = "scope"
    scope_row_element = FlashElement(
        key=scope_row_key,
        get_rect_in_window=lambda window: None,
        source_id="delegate:scope",
        skip_overlay_paint=True,
        hierarchical_key_prefix=True,
        delegate_widget=delegate_view,
        get_model_index=Index,
    )
    scope_overlay = type(
        "Overlay",
        (),
        {
            "_elements": {
                scope_row_key: [scope_row_element],
            },
            "_hierarchical_delegate_keys": {scope_row_key},
        },
    )()

    scope_overlay_keys = coordinator._overlay_flash_keys(scope_overlay, {descendant_key})

    assert scope_overlay_keys == {scope_row_key}
    assert (
        coordinator.get_computed_color_for_object_state_path(scope_row_key)
        == descendant_color
    )

    unscoped_ancestor_key = "fiji_streaming_config"
    unscoped_descendant_key = "fiji_streaming_config.batch_size"
    unscoped_element = FlashElement(
        key=unscoped_ancestor_key,
        get_rect_in_window=lambda window: None,
        source_id="delegate:fiji_streaming_config",
        skip_overlay_paint=True,
        hierarchical_key_prefix=True,
        delegate_widget=delegate_view,
        get_model_index=Index,
    )
    unscoped_overlay = type(
        "Overlay",
        (),
        {
            "_elements": {
                unscoped_ancestor_key: [unscoped_element],
            },
            "_hierarchical_delegate_keys": {unscoped_ancestor_key},
        },
    )()
    unscoped_color = QColor(20, 30, 40, 130)
    coordinator._computed_colors[unscoped_descendant_key] = unscoped_color

    unscoped_overlay_keys = coordinator._overlay_flash_keys(
        unscoped_overlay,
        {unscoped_descendant_key},
    )

    assert unscoped_overlay_keys == {unscoped_ancestor_key}
    assert (
        coordinator.get_computed_color_for_object_state_path(unscoped_ancestor_key)
        == unscoped_color
    )


def test_config_hierarchy_tree_row_flashes_from_unscoped_descendant_path(qapp) -> None:
    """Global config hierarchy rows use the same ObjectState path flashes as forms."""
    from dataclasses import field

    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtWidgets import QDialog, QVBoxLayout
    from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type
    from pyqt_reactive.animation.flash_mixin import (
        WindowFlashOverlay,
        _GlobalFlashCoordinator,
    )
    from pyqt_reactive.forms.parameter_form_manager import (
        FormManagerConfig,
        ParameterFormManager,
    )
    from pyqt_reactive.theming import ColorScheme
    from pyqt_reactive.widgets.shared.config_hierarchy_tree import (
        TREE_OBJECT_STATE_PATH_ROLE,
        ConfigHierarchyTreeHelper,
    )

    @dataclass
    class ChildConfig:
        value: int = 1

    @dataclass
    class RootConfig:
        child: ChildConfig = field(default_factory=ChildConfig)

    set_base_config_type(RootConfig)
    ObjectStateRegistry.clear()
    coordinator = _GlobalFlashCoordinator.get()
    coordinator._computed_colors.clear()
    coordinator._flash_start_times.clear()
    coordinator._pending_flash_keys.clear()

    host = QDialog()
    layout = QVBoxLayout(host)
    manager = ParameterFormManager(
        ObjectState(RootConfig()),
        FormManagerConfig(
            color_scheme=ColorScheme(),
            use_scroll_area=False,
        ),
    )
    tree = ConfigHierarchyTreeHelper().create_tree_from_root_dataclass(
        root_dataclass=RootConfig,
        form_manager=manager,
        state=manager.state,
        on_item_double_clicked=lambda _item, _column: None,
    )
    layout.addWidget(tree)
    layout.addWidget(manager)
    host.show()
    WindowFlashOverlay.get_for_window(host)

    try:
        for _ in range(20):
            qapp.processEvents()

        item = tree.topLevelItem(0)
        assert item is not None
        assert item.data(0, TREE_OBJECT_STATE_PATH_ROLE) == "child"

        manager.queue_flash_local("child")
        loop = QEventLoop()
        QTimer.singleShot(50, loop.quit)
        loop.exec()

        assert manager.get_flash_color_for_object_state_path("child") is not None
        coordinator._flash_start_times.clear()
        coordinator._pending_flash_keys.clear()
        coordinator._computed_colors.clear()

        manager.queue_flash_local("child.value")
        loop = QEventLoop()
        QTimer.singleShot(50, loop.quit)
        loop.exec()

        assert manager.get_flash_color_for_object_state_path("child") is not None
    finally:
        if coordinator._timer is not None:
            coordinator._timer.stop()
        coordinator._flash_start_times.clear()
        coordinator._pending_flash_keys.clear()
        coordinator._computed_colors.clear()
        coordinator._active_windows.clear()
        WindowFlashOverlay.cleanup_window(host)
        host.deleteLater()
        manager.deleteLater()
        ObjectStateRegistry.clear()


def test_widget_rect_flash_element_paints_visible_pixels_over_children(qapp) -> None:
    """Widget-rect flashes paint the target section itself, including child tables."""
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QDialog, QGroupBox, QTableWidget, QVBoxLayout

    from pyqt_reactive.animation.flash_mixin import (
        WindowFlashOverlay,
        _GlobalFlashCoordinator,
        create_widget_rect_element,
    )

    coordinator = _GlobalFlashCoordinator.get()
    coordinator._computed_colors.clear()
    coordinator._flash_start_times.clear()

    dialog = QDialog()
    dialog.resize(320, 220)
    layout = QVBoxLayout(dialog)
    section = QGroupBox("")
    section.setStyleSheet(
        "QGroupBox { background: rgb(30, 30, 30); border: 1px solid rgb(80, 80, 80); }"
    )
    section_layout = QVBoxLayout(section)
    table = QTableWidget(2, 2)
    section_layout.addWidget(table)
    layout.addWidget(section)
    dialog.show()

    for _ in range(10):
        qapp.processEvents()

    overlay = WindowFlashOverlay.get_for_window(section)
    assert overlay is not None
    element = create_widget_rect_element("section", section)
    overlay.register_element(element)
    assert element.get_child_rects is None

    table_center = table.mapTo(dialog, table.rect().center())
    rect = element.get_rect_in_window(dialog)
    assert rect is not None
    assert rect.contains(table_center)

    baseline = overlay.grab().toImage().pixelColor(table_center)
    coordinator._computed_colors["section"] = QColor(255, 0, 0, 180)
    overlay._invalidate_geometry_cache()
    overlay.repaint()
    qapp.processEvents()
    painted = overlay.grab().toImage().pixelColor(table_center)

    assert painted != baseline
    assert painted.red() > painted.green()
    assert painted.alpha() > 0

    coordinator._computed_colors.clear()
    WindowFlashOverlay.cleanup_window(dialog)
    dialog.close()


def test_flash_coordinator_batches_queue_calls_until_event_loop(qapp) -> None:
    """Independent flash callers in one UI turn commit as one timestamped batch."""

    from pyqt_reactive.animation.flash_mixin import _GlobalFlashCoordinator

    coordinator = _GlobalFlashCoordinator.get()
    if coordinator._timer is not None:
        coordinator._timer.stop()
    coordinator._computed_colors.clear()
    coordinator._flash_start_times.clear()
    coordinator._active_windows.clear()
    coordinator._pending_flash_keys.clear()
    coordinator._pending_flash_flush_scheduled = False

    coordinator.queue_flash("scope::first")
    coordinator.queue_flash_batch(("scope::second", "scope::third"))

    assert coordinator._flash_start_times == {}
    assert tuple(coordinator._pending_flash_keys) == (
        "scope::first",
        "scope::second",
        "scope::third",
    )

    for _ in range(3):
        qapp.processEvents()

    timestamps = tuple(coordinator._flash_start_times.values())
    assert len(timestamps) == 3
    assert len(set(timestamps)) == 1
    assert coordinator._pending_flash_keys == {}
    assert coordinator._pending_flash_flush_scheduled is False

    if coordinator._timer is not None:
        coordinator._timer.stop()
    coordinator._computed_colors.clear()
    coordinator._flash_start_times.clear()
    coordinator._active_windows.clear()


def test_groupbox_flash_cache_invalidates_when_mask_child_geometry_changes(qapp) -> None:
    """Cached rounded mask paths track child label/button geometry changes."""

    from PyQt6.QtWidgets import QDialog, QGroupBox, QLabel, QPushButton, QVBoxLayout

    from pyqt_reactive.animation.flash_mixin import (
        WindowFlashOverlay,
        _GlobalFlashCoordinator,
        create_groupbox_element,
    )

    coordinator = _GlobalFlashCoordinator.get()
    coordinator._computed_colors.clear()
    coordinator._flash_start_times.clear()

    dialog = QDialog()
    dialog.resize(360, 180)
    layout = QVBoxLayout(dialog)
    section = QGroupBox("Section")
    section_layout = QVBoxLayout(section)
    label = QLabel("Name")
    button = QPushButton("Reset")
    section_layout.addWidget(label)
    section_layout.addWidget(button)
    layout.addWidget(section)
    dialog.show()

    for _ in range(10):
        qapp.processEvents()

    overlay = WindowFlashOverlay.get_for_window(section)
    assert overlay is not None
    element = create_groupbox_element(
        "section.name",
        section,
        leaf_widget=button,
        label_widget=label,
    )
    overlay.register_element(element)
    overlay._rebuild_geometry_cache(
        overlay._get_scroll_area_clip_rects(),
        {"section.name"},
    )
    assert "section.name" in overlay._cache.element_rects

    label.setText("A much wider label that changes the mask geometry")
    label.adjustSize()
    button.setText("Reset inherited value")
    button.adjustSize()
    for _ in range(3):
        qapp.processEvents()

    assert "section.name" not in overlay._cache.element_rects

    WindowFlashOverlay.cleanup_window(dialog)
    dialog.close()


def test_groupbox_flash_cache_ignores_size_hint_only_text_changes(qapp) -> None:
    """Rendered placeholder/text churn does not rebuild flash geometry by itself."""

    from PyQt6.QtWidgets import QDialog, QGroupBox, QLabel, QPushButton, QVBoxLayout

    from pyqt_reactive.animation.flash_mixin import (
        WindowFlashOverlay,
        _GlobalFlashCoordinator,
        create_groupbox_element,
    )

    coordinator = _GlobalFlashCoordinator.get()
    coordinator._computed_colors.clear()
    coordinator._flash_start_times.clear()

    dialog = QDialog()
    dialog.resize(360, 180)
    layout = QVBoxLayout(dialog)
    section = QGroupBox("Section")
    section_layout = QVBoxLayout(section)
    label = QLabel("Name")
    button = QPushButton("Reset")
    section_layout.addWidget(label)
    section_layout.addWidget(button)
    layout.addWidget(section)
    dialog.show()

    for _ in range(10):
        qapp.processEvents()

    label.setFixedSize(label.size())
    button.setFixedSize(button.size())

    overlay = WindowFlashOverlay.get_for_window(section)
    assert overlay is not None
    overlay.register_element(
        create_groupbox_element(
            "section.name",
            section,
            leaf_widget=button,
            label_widget=label,
        )
    )
    overlay._rebuild_geometry_cache(
        overlay._get_scroll_area_clip_rects(),
        {"section.name"},
    )
    cached_rects = overlay._cache.element_rects["section.name"]
    cached_regions = overlay._cache.element_regions["section.name"]

    label.setText("A much wider label that changes sizeHint but not geometry")
    button.setText("Reset inherited value with a longer label")
    for _ in range(3):
        qapp.processEvents()

    assert overlay._cache.element_rects["section.name"] is cached_rects
    assert overlay._cache.element_regions["section.name"] is cached_regions

    label.setFixedSize(label.width() + 8, label.height())
    for _ in range(3):
        qapp.processEvents()

    assert "section.name" not in overlay._cache.element_rects

    WindowFlashOverlay.cleanup_window(dialog)
    dialog.close()


def test_full_groupbox_flash_uses_unmasked_visual_source(qapp) -> None:
    """Full groupbox flashes paint the whole rounded widget without child subtraction."""

    from PyQt6.QtWidgets import QDialog, QGroupBox, QLabel, QVBoxLayout

    from pyqt_reactive.animation.flash_mixin import create_groupbox_element

    dialog = QDialog()
    layout = QVBoxLayout(dialog)
    section = QGroupBox("Section")
    section_layout = QVBoxLayout(section)
    section_layout.addWidget(QLabel("Value"))
    layout.addWidget(section)
    dialog.show()

    for _ in range(3):
        qapp.processEvents()

    masked = create_groupbox_element("section", section)
    full = create_groupbox_element("section.enabled", section, use_full_rect=True)

    assert masked.get_child_rects is not None
    assert full.get_child_rects is None
    assert masked.source_id != full.source_id
    assert full.layout_watch_widgets == (section,)

    dialog.close()


def test_structural_masked_flash_invalidates_only_declared_geometry(qapp) -> None:
    """Structural masked flashes watch exact target geometry, not all descendants."""

    from PyQt6.QtWidgets import QDialog, QGroupBox, QLabel, QPushButton, QVBoxLayout

    from pyqt_reactive.animation.flash_mixin import (
        WindowFlashOverlay,
        create_structural_masked_container_element,
        get_child_mask_rect,
    )

    dialog = QDialog()
    dialog.resize(420, 240)
    layout = QVBoxLayout(dialog)
    section = QGroupBox("Section")
    section_layout = QVBoxLayout(section)
    target_label = QLabel("Enabled")
    unrelated_buttons = tuple(QPushButton(f"Unrelated {index}") for index in range(12))
    section_layout.addWidget(target_label)
    for button in unrelated_buttons:
        section_layout.addWidget(button)
    layout.addWidget(section)
    dialog.show()

    for _ in range(10):
        qapp.processEvents()
    section.setFixedSize(section.size())
    for button in unrelated_buttons:
        button.setFixedSize(button.size())

    def mask_rects(window):
        return ((get_child_mask_rect(target_label, window), False),)

    overlay = WindowFlashOverlay.get_for_window(section)
    assert overlay is not None
    overlay.register_element(
        create_structural_masked_container_element(
            "section.enabled",
            section,
            mask_rects,
            layout_watch_widgets=(target_label,),
        )
    )
    overlay._rebuild_geometry_cache(
        overlay._get_scroll_area_clip_rects(),
        {"section.enabled"},
    )
    cached_rects = overlay._cache.element_rects["section.enabled"]
    cached_regions = overlay._cache.element_regions["section.enabled"]

    unrelated_buttons[0].move(
        unrelated_buttons[0].x() + 1,
        unrelated_buttons[0].y(),
    )
    for _ in range(3):
        qapp.processEvents()

    assert overlay._cache.element_rects["section.enabled"] is cached_rects
    assert overlay._cache.element_regions["section.enabled"] is cached_regions

    target_label.setFixedWidth(target_label.width() + 24)
    for _ in range(3):
        qapp.processEvents()

    assert "section.enabled" not in overlay._cache.element_rects

    WindowFlashOverlay.cleanup_window(dialog)
    dialog.close()


def test_flash_region_cache_reuses_steady_state_key_set(qapp, monkeypatch) -> None:
    """Repeated animation frames reuse the derived region for unchanged active keys."""

    from PyQt6.QtWidgets import QDialog, QGroupBox, QLabel, QVBoxLayout

    from pyqt_reactive.animation.flash_mixin import (
        WindowFlashOverlay,
        create_groupbox_element,
    )

    dialog = QDialog()
    layout = QVBoxLayout(dialog)
    section = QGroupBox("Section")
    section_layout = QVBoxLayout(section)
    section_layout.addWidget(QLabel("Value"))
    layout.addWidget(section)
    dialog.show()

    for _ in range(10):
        qapp.processEvents()

    overlay = WindowFlashOverlay.get_for_window(section)
    assert overlay is not None
    overlay.register_element(create_groupbox_element("section", section))

    calls = 0
    original_visible_paint_records = overlay._visible_paint_records

    def counted_visible_paint_records(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_visible_paint_records(*args, **kwargs)

    monkeypatch.setattr(
        overlay,
        "_visible_paint_records",
        counted_visible_paint_records,
    )

    first = overlay._flash_region_for_keys({"section"})
    second = overlay._flash_region_for_keys({"section"})

    assert calls == 1
    assert first[1:3] == second[1:3]
    assert frozenset({"section"}) in overlay._cache.flash_regions

    WindowFlashOverlay.cleanup_window(dialog)
    dialog.close()


def test_visual_frame_callbacks_coalesce_by_owner(qapp) -> None:
    """Shared visual-frame callbacks keep one pending update per owner."""

    from PyQt6.QtCore import QObject

    from pyqt_reactive.animation import queue_visual_frame_callback

    owner = QObject()
    calls = []

    queue_visual_frame_callback(owner, lambda: calls.append("first"))
    queue_visual_frame_callback(owner, lambda: calls.append("second"))

    for _ in range(3):
        qapp.processEvents()

    assert calls == ["second"]


def test_overlay_batches_multiple_keys_for_same_visual_source(qapp) -> None:
    """One visual target registered under multiple keys paints as one source."""

    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QDialog, QGroupBox, QLabel, QVBoxLayout

    from pyqt_reactive.animation.flash_mixin import (
        WindowFlashOverlay,
        _GlobalFlashCoordinator,
        create_groupbox_element,
    )

    coordinator = _GlobalFlashCoordinator.get()
    coordinator._computed_colors.clear()
    coordinator._flash_start_times.clear()

    dialog = QDialog()
    dialog.resize(320, 180)
    layout = QVBoxLayout(dialog)
    section = QGroupBox("Section")
    section_layout = QVBoxLayout(section)
    section_layout.addWidget(QLabel("Value"))
    layout.addWidget(section)
    dialog.show()

    for _ in range(10):
        qapp.processEvents()

    overlay = WindowFlashOverlay.get_for_window(section)
    assert overlay is not None
    overlay.register_element(create_groupbox_element("section", section))
    overlay.register_element(create_groupbox_element("section.enabled", section))
    overlay._rebuild_geometry_cache(
        overlay._get_scroll_area_clip_rects(),
        {"section", "section.enabled"},
    )

    records, visible_key_count = overlay._visible_paint_records(
        {"section", "section.enabled"},
        colors={
            "section": QColor(255, 0, 0, 20),
            "section.enabled": QColor(255, 0, 0, 180),
        },
    )

    assert visible_key_count == 2
    assert len(records) == 1
    assert records[0].key == "section.enabled"
    assert records[0].color is not None
    assert records[0].color.alpha() == 180

    region, _, rect_count, *_ = overlay._flash_region_for_keys(
        {"section", "section.enabled"}
    )
    assert not region.isEmpty()
    assert rect_count == 1

    WindowFlashOverlay.cleanup_window(dialog)
    dialog.close()


def test_flash_registration_skips_factory_for_existing_visual_source(qapp) -> None:
    """Duplicate widget-source registration avoids rebuilding the flash element."""

    from PyQt6.QtWidgets import QDialog, QVBoxLayout, QWidget

    from pyqt_reactive.animation.flash_mixin import (
        FlashElement,
        VisualUpdateMixin,
        WindowFlashOverlay,
    )

    class FlashManager(QWidget, VisualUpdateMixin):
        def __init__(self) -> None:
            super().__init__()
            self._init_visual_update_mixin()

        def _execute_text_update(self) -> None:
            pass

    dialog = QDialog()
    layout = QVBoxLayout(dialog)
    manager = FlashManager()
    layout.addWidget(manager)
    dialog.show()

    for _ in range(3):
        qapp.processEvents()

    overlay = WindowFlashOverlay.get_for_window(manager)
    assert overlay is not None

    calls = 0

    def make_element(key: str) -> FlashElement:
        nonlocal calls
        calls += 1
        return FlashElement(
            key=key,
            get_rect_in_window=lambda _window: None,
            source_id="widget-source",
        )

    manager._register_flash_element_internal(
        "field",
        make_element,
        manager,
        source_id_factory=lambda _key: "widget-source",
    )
    manager._register_flash_element_internal(
        "field",
        make_element,
        manager,
        source_id_factory=lambda _key: "widget-source",
    )

    assert calls == 1
    assert len(overlay._elements["field"]) == 1

    WindowFlashOverlay.cleanup_window(dialog)
    dialog.close()


def test_flash_overlay_cleanup_detaches_refreshed_event_sources(
    qapp,
    monkeypatch,
) -> None:
    """Cleanup detaches retained event sources even after scroll discovery refreshes."""
    import sys

    from PyQt6.QtWidgets import QDialog, QScrollArea, QVBoxLayout, QWidget

    from pyqt_reactive.animation.flash_mixin import (
        WindowFlashOverlay,
        create_widget_rect_element,
    )

    dialog = QDialog()
    layout = QVBoxLayout(dialog)
    initial_scroll = QScrollArea(dialog)
    initial_viewport = QWidget()
    initial_scroll.setViewport(initial_viewport)
    watched = QWidget(dialog)
    layout.addWidget(initial_scroll)
    layout.addWidget(watched)
    dialog.show()
    qapp.processEvents()

    overlay = WindowFlashOverlay.get_for_window(watched)
    assert overlay is not None
    overlay.register_element(create_widget_rect_element("field", watched))

    layout.removeWidget(initial_scroll)
    initial_scroll.setParent(None)
    replacement_scroll = QScrollArea(dialog)
    replacement_viewport = QWidget()
    replacement_scroll.setViewport(replacement_viewport)
    layout.addWidget(replacement_scroll)
    overlay._refresh_scroll_area_event_filters()

    registered_source_ids = set(overlay._event_filter_sources)
    assert {
        id(dialog),
        id(initial_viewport),
        id(replacement_viewport),
        id(watched),
    } <= registered_source_ids

    uncaught: list[BaseException] = []
    monkeypatch.setattr(
        sys,
        "excepthook",
        lambda _type, value, _traceback: uncaught.append(value),
    )
    WindowFlashOverlay.cleanup_window(dialog)
    assert overlay._event_filter_sources == {}

    cache = overlay._cache
    del overlay._cache
    QWidget(dialog)
    QWidget(initial_viewport)
    QWidget(replacement_viewport)
    QWidget(watched)
    qapp.processEvents()
    overlay._cache = cache

    assert uncaught == []

    initial_scroll.deleteLater()
    dialog.deleteLater()
    qapp.processEvents()


def test_flash_lifecycle_cleanup_survives_owner_deletion_and_recreation(
    qapp,
    monkeypatch,
) -> None:
    """Destroyed targets clean captured flash state without dereferencing the owner."""
    import sys

    from PyQt6 import sip
    from PyQt6.QtCore import QCoreApplication, QEvent
    from PyQt6.QtWidgets import QDialog, QVBoxLayout, QWidget

    from pyqt_reactive.animation.flash_mixin import (
        VisualUpdateMixin,
        WindowFlashOverlay,
        widget_rect_flash_source_id,
    )

    class DeletionSensitiveFlashManager(QWidget, VisualUpdateMixin):
        def __init__(self, parent: QWidget) -> None:
            super().__init__(parent)
            self._simulate_deleted_wrapper = False
            self._init_visual_update_mixin()

        def __getattribute__(self, name: str):
            if name in {
                "_flash_registrations",
                "_flash_registration_lifecycle_keys",
            } and object.__getattribute__(self, "_simulate_deleted_wrapper"):
                raise RuntimeError(
                    "wrapped C/C++ object of type "
                    "DeletionSensitiveFlashManager has been deleted"
                )
            return super().__getattribute__(name)

    dialog = QDialog()
    layout = QVBoxLayout(dialog)
    manager = DeletionSensitiveFlashManager(dialog)
    target = QWidget(dialog)
    layout.addWidget(manager)
    layout.addWidget(target)
    dialog.show()
    qapp.processEvents()

    manager.register_flash_widget_rect("field", target)
    overlay = WindowFlashOverlay.get_for_window(target)
    assert overlay is not None
    source_id = widget_rect_flash_source_id(target)
    assert overlay.has_element_source("field", source_id)
    registrations = manager._flash_registrations
    lifecycle_keys = manager._flash_registration_lifecycle_keys

    uncaught: list[BaseException] = []
    monkeypatch.setattr(
        sys,
        "excepthook",
        lambda _type, value, _traceback: uncaught.append(value),
    )
    manager._simulate_deleted_wrapper = True
    manager.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(manager)
    target.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()

    assert uncaught == []
    assert registrations == []
    assert lifecycle_keys == set()
    assert not overlay.has_element_source("field", source_id)

    replacement = DeletionSensitiveFlashManager(dialog)
    replacement_target = QWidget(dialog)
    layout.addWidget(replacement)
    layout.addWidget(replacement_target)
    replacement.register_flash_widget_rect("field", replacement_target)
    replacement_source_id = widget_rect_flash_source_id(replacement_target)
    assert overlay.has_element_source("field", replacement_source_id)

    replacement_target.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    assert replacement._flash_registrations == []
    assert replacement._flash_registration_lifecycle_keys == set()
    assert not overlay.has_element_source("field", replacement_source_id)

    replacement.deleteLater()
    WindowFlashOverlay.cleanup_window(dialog)
    dialog.close()


def test_flash_lifecycle_cleanup_static_ast_has_no_owner_reference() -> None:
    """Destroyed-signal cleanup must not dereference its deleted mixin owner."""
    import ast
    import inspect
    import textwrap

    from pyqt_reactive.animation.flash_mixin import VisualUpdateMixin

    source = textwrap.dedent(
        inspect.getsource(VisualUpdateMixin._cleanup_flash_registration)
    )
    method = ast.parse(source).body[0]

    assert isinstance(method, ast.FunctionDef)
    assert any(
        isinstance(decorator, ast.Name) and decorator.id == "staticmethod"
        for decorator in method.decorator_list
    )
    assert not any(
        isinstance(node, ast.Name) and node.id == "self"
        for node in ast.walk(method)
    )


def test_geometry_rebuild_reuses_duplicate_visual_source(qapp) -> None:
    """Fanout keys sharing one source reuse the same expensive geometry build."""

    from PyQt6.QtCore import QRect
    from PyQt6.QtWidgets import QDialog, QVBoxLayout, QWidget

    from pyqt_reactive.animation.flash_mixin import FlashElement, WindowFlashOverlay

    dialog = QDialog()
    dialog.resize(240, 160)
    layout = QVBoxLayout(dialog)
    owner = QWidget()
    owner.setMinimumSize(120, 80)
    layout.addWidget(owner)
    dialog.show()

    for _ in range(3):
        qapp.processEvents()

    overlay = WindowFlashOverlay.get_for_window(owner)
    assert overlay is not None

    child_rect_calls = 0

    def rect_for_window(_window: QWidget) -> QRect:
        return QRect(20, 20, 100, 60)

    def child_rects_for_window(_window: QWidget) -> list[tuple[QRect, bool]]:
        nonlocal child_rect_calls
        child_rect_calls += 1
        return [(QRect(30, 30, 20, 10), False)]

    overlay.register_element(
        FlashElement(
            key="field",
            get_rect_in_window=rect_for_window,
            get_child_rects=child_rects_for_window,
            source_id="shared-source",
            corner_radius=4,
        )
    )
    overlay.register_element(
        FlashElement(
            key="field.enabled",
            get_rect_in_window=rect_for_window,
            get_child_rects=child_rects_for_window,
            source_id="shared-source",
            corner_radius=4,
        )
    )

    overlay._rebuild_geometry_cache([], {"field", "field.enabled"})

    assert child_rect_calls == 1
    assert overlay._cache.element_rects["field"][0] is overlay._cache.element_rects["field.enabled"][0]
    assert overlay._cache.element_regions["field"][0] is overlay._cache.element_regions["field.enabled"][0]

    WindowFlashOverlay.cleanup_window(dialog)
    dialog.close()


def test_dynamic_flash_registration_rebuilds_valid_geometry_cache(qapp) -> None:
    """Newly registered elements paint even when the overlay cache was already valid."""
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QDialog, QGroupBox, QTableWidget, QVBoxLayout

    from pyqt_reactive.animation.flash_mixin import (
        WindowFlashOverlay,
        _GlobalFlashCoordinator,
        create_widget_rect_element,
    )

    coordinator = _GlobalFlashCoordinator.get()
    coordinator._computed_colors.clear()
    coordinator._flash_start_times.clear()

    dialog = QDialog()
    dialog.resize(320, 220)
    layout = QVBoxLayout(dialog)
    section = QGroupBox("")
    section_layout = QVBoxLayout(section)
    table = QTableWidget(2, 2)
    section_layout.addWidget(table)
    layout.addWidget(section)
    dialog.show()

    for _ in range(10):
        qapp.processEvents()

    overlay = WindowFlashOverlay.get_for_window(section)
    assert overlay is not None

    # Simulate an already-valid cache from a previous flash.
    overlay._cache.valid = True
    overlay._cache.element_rects.clear()
    overlay._cache.element_regions.clear()

    element = create_widget_rect_element("section", section)
    overlay.register_element(element)
    assert not overlay._cache.valid

    table_center = table.mapTo(dialog, table.rect().center())
    baseline = overlay.grab().toImage().pixelColor(table_center)
    coordinator._computed_colors["section"] = QColor(255, 0, 0, 180)
    overlay.repaint()
    qapp.processEvents()
    painted = overlay.grab().toImage().pixelColor(table_center)

    assert painted != baseline
    assert painted.red() > painted.green()

    coordinator._computed_colors.clear()
    WindowFlashOverlay.cleanup_window(dialog)
    dialog.close()


def test_local_widget_rect_queue_paints_after_timer_tick(qapp) -> None:
    """The real local queue path must produce visible overlay pixels."""
    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtWidgets import QDialog, QGroupBox, QVBoxLayout, QWidget

    from pyqt_reactive.animation.flash_mixin import (
        VisualUpdateMixin,
        WindowFlashOverlay,
        _GlobalFlashCoordinator,
    )

    class FlashManager(QWidget, VisualUpdateMixin):
        def __init__(self) -> None:
            super().__init__()
            self.scope_id = "scope"
            self._init_visual_update_mixin()

        def _execute_text_update(self) -> None:
            pass

    coordinator = _GlobalFlashCoordinator.get()
    coordinator._computed_colors.clear()
    coordinator._flash_start_times.clear()
    coordinator._active_windows.clear()

    dialog = QDialog()
    dialog.resize(320, 220)
    layout = QVBoxLayout(dialog)
    manager = FlashManager()
    manager_layout = QVBoxLayout(manager)
    section = QGroupBox("Section")
    section.setStyleSheet(
        "QGroupBox { background: rgb(30, 30, 30); border: 1px solid rgb(80, 80, 80); }"
    )
    section_layout = QVBoxLayout(section)
    child = QWidget()
    child.setMinimumSize(100, 60)
    section_layout.addWidget(child)
    manager_layout.addWidget(section)
    layout.addWidget(manager)
    dialog.show()

    for _ in range(10):
        qapp.processEvents()

    manager.register_flash_widget_rect("section", section)
    overlay = WindowFlashOverlay.get_for_window(section)
    assert overlay is not None
    sample_point = section.mapTo(dialog, section.rect().center())
    baseline = overlay.grab().toImage().pixelColor(sample_point)

    manager.queue_flash_local("section")
    loop = QEventLoop()
    QTimer.singleShot(80, loop.quit)
    loop.exec()
    qapp.processEvents()

    painted = overlay.grab().toImage().pixelColor(sample_point)
    assert painted != baseline
    assert painted.alpha() > 0

    coordinator._computed_colors.clear()
    WindowFlashOverlay.cleanup_window(dialog)
    dialog.close()


def test_table_cell_flash_element_paints_visible_cell_pixels(qapp) -> None:
    """Structural table-cell flashes paint the target cell, not just queue metadata."""
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QDialog, QTableWidget, QTableWidgetItem, QVBoxLayout

    from pyqt_reactive.animation.flash_mixin import (
        WindowFlashOverlay,
        _GlobalFlashCoordinator,
        create_table_cell_element,
    )
    from pyqt_reactive.widgets.structural_table import StructuralTableCellTarget

    coordinator = _GlobalFlashCoordinator.get()
    coordinator._computed_colors.clear()
    coordinator._flash_start_times.clear()

    dialog = QDialog()
    dialog.resize(320, 180)
    layout = QVBoxLayout(dialog)
    table = QTableWidget(2, 2)
    table.setItem(0, 0, QTableWidgetItem("a"))
    table.setItem(0, 1, QTableWidgetItem("b"))
    layout.addWidget(table)
    dialog.show()

    for _ in range(10):
        qapp.processEvents()

    overlay = WindowFlashOverlay.get_for_window(table)
    assert overlay is not None
    target = StructuralTableCellTarget(table, 0, 1, table.cellWidget(0, 1))
    element = create_table_cell_element("cell", target)
    overlay.register_element(element)

    cell_rect = table.visualRect(table.model().index(0, 1))
    cell_center = table.viewport().mapTo(dialog, cell_rect.center())
    flash_rect = element.get_rect_in_window(dialog)
    assert flash_rect is not None
    assert flash_rect.contains(cell_center)

    baseline = overlay.grab().toImage().pixelColor(cell_center)
    coordinator._computed_colors["cell"] = QColor(255, 0, 0, 180)
    overlay._invalidate_geometry_cache()
    overlay.repaint()
    qapp.processEvents()
    painted = overlay.grab().toImage().pixelColor(cell_center)

    assert painted != baseline
    assert painted.red() > painted.green()
    assert painted.alpha() > 0

    coordinator._computed_colors.clear()
    WindowFlashOverlay.cleanup_window(dialog)
    dialog.close()


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


def test_widget_service_skips_equal_value_assignment(qapp):
    """Signal-blocked widget writes are skipped when ValueGettable reports equality."""
    from pyqt_reactive.forms.widget_strategies import NoneAwareLineEdit
    from pyqt_reactive.services.widget_service import WidgetService

    class EqualAwareWidget(NoneAwareLineEdit):
        def __init__(self):
            super().__init__()
            self.set_calls = []
            super().set_value("same")

        def set_value(self, value):
            self.set_calls.append(value)
            super().set_value(value)

    widget = EqualAwareWidget()
    service = WidgetService()

    service.update_widget_value(widget, "same")
    service.update_widget_value(widget, "new")

    assert widget.set_calls == ["new"]


def test_resolved_preview_placeholder_uses_cached_placeholder_text(qapp):
    """Inherited preview widgets are not repainted when placeholder text is unchanged."""
    from pyqt_reactive.forms.widget_strategies import (
        NoneAwareLineEdit,
        PyQt6WidgetEnhancer,
    )
    from pyqt_reactive.protocols import ResolvedValuePreviewSettable

    class PreviewWidget(NoneAwareLineEdit, ResolvedValuePreviewSettable):
        def __init__(self):
            super().__init__()
            self.preview_values = []

        def set_resolved_value_preview(self, value):
            self.preview_values.append(value)

    widget = PreviewWidget()

    PyQt6WidgetEnhancer.apply_placeholder_with_value(
        widget,
        "resolved",
        "Pipeline default: resolved",
    )
    PyQt6WidgetEnhancer.apply_placeholder_with_value(
        widget,
        "resolved",
        "Pipeline default: resolved",
    )

    assert widget.preview_values == ["resolved"]


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


def test_none_aware_int_edit_preserves_committed_value_during_invalid_text(qapp):
    """Reactive refreshes can inspect transient invalid text without crashing."""
    from PyQt6.QtGui import QValidator

    from pyqt_reactive.forms.widget_strategies import NoneAwareIntEdit
    from pyqt_reactive.services.widget_service import WidgetService

    widget = NoneAwareIntEdit()
    service = WidgetService()
    widget.set_value(7777)

    widget.setText("6665765765")
    state, _, _ = widget.validator().validate(widget.text(), 0)
    assert state != QValidator.State.Acceptable

    service.update_widget_value(widget, 7777)
    assert widget.text() == "6665765765"
    assert widget.get_value() == 7777

    service.update_widget_value(widget, 5555)
    assert widget.text() == "5555"
    assert widget.get_value() == 5555

    widget.set_value(None)
    assert widget.text() == ""
    assert widget.get_value() is None


def test_none_aware_int_edit_does_not_commit_invalid_text(qapp):
    """Only empty or validator-acceptable integer text reaches form state."""
    from PyQt6.QtCore import QEventLoop, QTimer

    from pyqt_reactive.forms.widget_strategies import NoneAwareIntEdit

    widget = NoneAwareIntEdit()
    widget.set_value(7777)
    values = []
    widget.connect_change_signal(values.append)

    widget.setText("6665765765")
    loop = QEventLoop()
    QTimer.singleShot(180, loop.quit)
    loop.exec()

    assert values == []
    assert widget.get_value() == 7777

    widget.setText("5555")
    loop = QEventLoop()
    QTimer.singleShot(180, loop.quit)
    loop.exec()

    assert values == [5555]
    assert widget.get_value() == 5555


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


def test_multiline_delegate_leading_marker_paints_visible_pixels(qapp):
    """Declared row markers render as visible debugger-style row chrome."""
    from PyQt6.QtCore import QRect, Qt
    from PyQt6.QtGui import QColor, QPainter, QPixmap
    from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QStyle, QStyleOptionViewItem
    from pyqt_reactive.widgets.shared.list_item_delegate import (
        LEADING_MARKER_ROLE,
        MultilinePreviewItemDelegate,
        ListItemLeadingMarker,
    )
    from pyqt_reactive.widgets.shared.scope_visual_config import get_scope_visual_config

    item_list = QListWidget()
    item = QListWidgetItem("Current frame")
    item.setData(LEADING_MARKER_ROLE, ListItemLeadingMarker())
    item_list.addItem(item)
    delegate = MultilinePreviewItemDelegate(
        QColor("black"),
        QColor("gray"),
        QColor("white"),
        parent=item_list,
    )
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 320, 44)
    option.font = item_list.font()
    option.state = QStyle.StateFlag.State_Enabled
    option.widget = item_list
    index = item_list.model().index(0, 0)

    pixmap = QPixmap(340, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        delegate.paint(painter, option, index)
    finally:
        painter.end()

    config = get_scope_visual_config()
    marker_pixel = pixmap.toImage().pixelColor(
        config.LIST_ITEM_LEADING_MARKER_STRIPE_LEFT_PX,
        option.rect.center().y(),
    )

    assert marker_pixel.alpha() > 0
    assert marker_pixel.green() > marker_pixel.red()


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
