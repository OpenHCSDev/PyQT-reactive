"""Tests for reusable inline dataclass ObjectState chrome."""

from __future__ import annotations

from dataclasses import dataclass, field

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget


@dataclass(frozen=True, slots=True)
class InlineChildConfig:
    source_filters: tuple[str, ...] | None = None
    enabled: bool | None = None


@dataclass(frozen=True, slots=True)
class InlineHolder:
    config: InlineChildConfig = field(default_factory=InlineChildConfig)


@dataclass
class InlineBaseConfig:
    pass


def _manager_for_holder():
    from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type
    from pyqt_reactive.forms.parameter_form_manager import (
        FormManagerConfig,
        ParameterFormManager,
    )
    from pyqt_reactive.protocols import (
        PyQtWidgetMeta,
        RawResolvedValueSettable,
        ValueSettable,
    )
    from pyqt_reactive.theming import ColorScheme

    class InlineOwnerWidget(
        QWidget,
        ValueSettable,
        RawResolvedValueSettable,
        metaclass=PyQtWidgetMeta,
    ):
        """Nominal owner-widget contract used by context-only tests."""

        def __init__(self) -> None:
            super().__init__()
            self.value = None
            self.resolved_value = None

        def set_value(self, value) -> None:
            self.value = value

        def set_raw_value_with_resolved_preview(
            self,
            raw_value,
            resolved_value,
        ) -> None:
            self.value = raw_value
            self.resolved_value = resolved_value

    set_base_config_type(InlineBaseConfig)
    state = ObjectState(InlineHolder(), scope_id="inline-dataclass-test")
    ObjectStateRegistry.register(state, _skip_snapshot=True)
    manager = ParameterFormManager(
        state=state,
        config=FormManagerConfig(
            color_scheme=ColorScheme(),
            use_scroll_area=False,
        ),
    )
    # These tests construct InlineDataclassFormContext directly instead of
    # going through the registered inline-widget creation pipeline. Install
    # the same explicit value-setting contract that InlineDataclassGroupBox
    # provides in production; a normal nested GroupBoxWithHelp is only chrome.
    manager.widgets["config"] = InlineOwnerWidget()
    return manager


def _inline_param_info():
    from pyqt_reactive.forms.parameter_info_types import InlineDataclassWidgetInfo

    return InlineDataclassWidgetInfo(
        name="config",
        type=InlineChildConfig,
        current_value=InlineChildConfig(),
        default_value=InlineChildConfig(),
    )


def test_inline_dataclass_context_uses_typed_child_paths_and_resets(qapp) -> None:
    from objectstate import ObjectStateRegistry
    from pyqt_reactive.forms.inline_dataclass_context import (
        InlineDataclassFormContext,
    )

    manager = _manager_for_holder()
    try:
        context = InlineDataclassFormContext.from_inline_widget(
            manager=manager,
            param_info=_inline_param_info(),
            current_value=InlineChildConfig(),
        )

        identity = context.child_identity("source_filters")

        assert identity.object_state_path.value == "config.source_filters"
        assert identity.manager_path.value == "config.source_filters"
        assert identity.owner_type is InlineChildConfig

        manager.state.update_parameter(
            "config",
            InlineChildConfig(source_filters=("DAPI",)),
        )
        assert context.raw_child_value("source_filters") == ("DAPI",)
        assert context.resolved_child_value("source_filters") == ("DAPI",)

        context.reset_child("source_filters")

        assert manager.state.parameters["config"].source_filters is None
        assert manager.state.parameters["config.source_filters"] is None
    finally:
        manager.deleteLater()
        ObjectStateRegistry.clear()


def test_inline_dataclass_reset_child_is_noop_when_raw_child_already_default(qapp) -> None:
    from unittest.mock import patch

    from objectstate import ObjectStateRegistry
    from pyqt_reactive.forms.inline_dataclass_context import (
        InlineDataclassFormContext,
    )

    manager = _manager_for_holder()
    try:
        context = InlineDataclassFormContext.from_inline_widget(
            manager=manager,
            param_info=_inline_param_info(),
            current_value=InlineChildConfig(),
        )

        with patch.object(manager, "update_parameter") as update_parameter:
            context.reset_child("source_filters")

        update_parameter.assert_not_called()
        assert manager.state.parameters["config.source_filters"] is None
    finally:
        manager.deleteLater()
        ObjectStateRegistry.clear()


def test_inline_dataclass_reset_child_delegates_without_direct_chrome_refresh(qapp) -> None:
    from unittest.mock import patch

    from objectstate import ObjectStateRegistry
    from pyqt_reactive.forms.inline_dataclass_context import (
        InlineDataclassFormContext,
    )

    manager = _manager_for_holder()
    try:
        context = InlineDataclassFormContext.from_inline_widget(
            manager=manager,
            param_info=_inline_param_info(),
            current_value=InlineChildConfig(),
        )
        manager.state.update_parameter(
            "config",
            InlineChildConfig(source_filters=("DAPI",)),
        )

        with (
            patch.object(manager, "update_parameter") as update_parameter,
            patch.object(
                manager.chrome_sync,
                "refresh_widgets_for_paths",
            ) as refresh_widgets_for_paths,
        ):
            context.reset_child("source_filters")

        update_parameter.assert_called_once()
        assert update_parameter.call_args.args[0] == "config"
        assert update_parameter.call_args.args[1].source_filters is None
        refresh_widgets_for_paths.assert_not_called()
    finally:
        manager.deleteLater()
        ObjectStateRegistry.clear()


def test_inline_dataclass_child_chrome_refreshes_existing_marker_semantics(qapp) -> None:
    from objectstate import ObjectStateRegistry
    from pyqt_reactive.forms.inline_dataclass_chrome import InlineDataclassChildChrome
    from pyqt_reactive.forms.inline_dataclass_context import (
        InlineDataclassFormContext,
    )

    manager = _manager_for_holder()
    try:
        context = InlineDataclassFormContext.from_inline_widget(
            manager=manager,
            param_info=_inline_param_info(),
            current_value=InlineChildConfig(),
        )
        chrome = InlineDataclassChildChrome(context)
        chrome.create_section_header(
            title="Source Filters",
            field_name="source_filters",
        )
        section_group = QWidget()
        chrome.register_section_group("source_filters", section_group)

        manager.state.update_parameter(
            "config",
            InlineChildConfig(source_filters=("DAPI",)),
        )
        chrome.refresh_markers()

        identity = context.child_identity("source_filters")
        label = chrome.labels[identity]
        reset_button = chrome.reset_buttons[identity]

        assert label._dirty_label_state.is_dirty is True
        assert label._label.font().underline() is True
        assert reset_button.text() == "*Reset"
        assert reset_button.font().underline() is True
    finally:
        manager.deleteLater()
        section_group.deleteLater()
        ObjectStateRegistry.clear()


def test_inline_dataclass_groupbox_suppresses_programmatic_inner_changes(qapp) -> None:
    from pyqt_reactive.protocols import (
        ChangeSignalEmitter,
        PyQtWidgetMeta,
        ResolvedValuePreviewSettable,
        ValueGettable,
        ValueSettable,
    )
    from pyqt_reactive.widgets.shared.clickable_help_components import (
        InlineDataclassGroupBox,
    )

    class NoisyInlineWidget(
        QWidget,
        ValueGettable,
        ValueSettable,
        ResolvedValuePreviewSettable,
        ChangeSignalEmitter,
        metaclass=PyQtWidgetMeta,
    ):
        changed = pyqtSignal(object)

        def __init__(self) -> None:
            super().__init__()
            self._value = None

        def get_value(self):
            return self._value

        def set_value(self, value) -> None:
            self._value = value
            self.changed.emit(value)

        def set_resolved_value_preview(self, value) -> None:
            self._value = value
            self.changed.emit(value)

        def connect_change_signal(self, callback) -> None:
            self.changed.connect(callback)

        def disconnect_change_signal(self, callback) -> None:
            self.changed.disconnect(callback)

        def emit_user_change(self, value) -> None:
            self._value = value
            self.changed.emit(value)

    groupbox = InlineDataclassGroupBox("Inline")
    widget = NoisyInlineWidget()
    groupbox.set_value_widget(widget)
    received = []

    groupbox.connect_change_signal(received.append)

    groupbox.set_value("model")
    groupbox.set_resolved_value_preview("preview")
    widget.emit_user_change("user")

    assert received == ["user"]


def test_inline_dataclass_groupbox_skips_equal_resolved_preview(qapp) -> None:
    from pyqt_reactive.protocols import (
        ChangeSignalEmitter,
        PyQtWidgetMeta,
        ResolvedValuePreviewSettable,
        ValueGettable,
        ValueSettable,
    )
    from pyqt_reactive.widgets.shared.clickable_help_components import (
        InlineDataclassGroupBox,
    )

    class PreviewInlineWidget(
        QWidget,
        ValueGettable,
        ValueSettable,
        ResolvedValuePreviewSettable,
        ChangeSignalEmitter,
        metaclass=PyQtWidgetMeta,
    ):
        changed = pyqtSignal(object)

        def __init__(self) -> None:
            super().__init__()
            self._value = None
            self.preview_values = []

        def get_value(self):
            return self._value

        def set_value(self, value) -> None:
            self._value = value

        def set_resolved_value_preview(self, value) -> None:
            self.preview_values.append(value)
            self._value = value

        def connect_change_signal(self, callback) -> None:
            self.changed.connect(callback)

        def disconnect_change_signal(self, callback) -> None:
            self.changed.disconnect(callback)

    groupbox = InlineDataclassGroupBox("Inline")
    widget = PreviewInlineWidget()
    groupbox.set_value_widget(widget)

    groupbox.set_resolved_value_preview("preview")
    groupbox.set_resolved_value_preview("preview")
    groupbox.set_value("model")
    groupbox.set_resolved_value_preview("preview")

    assert widget.preview_values == ["preview", "preview"]
