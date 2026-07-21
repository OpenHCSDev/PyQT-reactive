"""Enabled-title relocation releases its original responsive form row."""

from __future__ import annotations

from dataclasses import dataclass, field

from PyQt6 import sip
from PyQt6.QtTest import QTest
from python_introspect import Enableable


@dataclass(frozen=True)
class ViewerConfig(Enableable):
    value_a: int = 1
    value_b: int = 2
    value_c: int = 3
    value_d: int = 4
    value_e: int = 5
    value_f: int = 6


@dataclass(frozen=True)
class RootConfig:
    viewer: ViewerConfig = field(default_factory=ViewerConfig)


def test_enableable_title_relocation_releases_responsive_source_row(qapp) -> None:
    """Title controls cannot remain owned by a body row after relocation."""

    from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type

    from pyqt_reactive.forms.parameter_form_manager import (
        FormManagerConfig,
        ParameterFormManager,
    )
    from pyqt_reactive.theming import ColorScheme
    from pyqt_reactive.widgets.shared.responsive_layout_widgets import (
        ResponsiveParameterRow,
    )
    set_base_config_type(RootConfig)
    ObjectStateRegistry.clear()
    manager = ParameterFormManager(
        ObjectState(RootConfig(), scope_id="enabled-title-row-owner"),
        FormManagerConfig(
            color_scheme=ColorScheme(),
            use_scroll_area=False,
        ),
    )
    manager.resize(420, 500)
    manager.show()

    try:
        for _ in range(200):
            qapp.processEvents()
            ready = (
                "viewer" in manager.nested_managers
                and "enabled" in manager.nested_managers["viewer"].widgets
            )
            if ready:
                break
            QTest.qWait(5)

        assert ready, (
            tuple(manager.nested_managers),
            tuple(manager.widgets),
            tuple(manager.nested_managers["viewer"].widgets),
            tuple(manager.nested_managers["viewer"].parameters),
        )
        for width in (240, 620, 300, 420):
            manager.resize(width, 500)
            QTest.qWait(50)
            qapp.processEvents()

        nested = manager.nested_managers["viewer"]
        container = manager.widgets["viewer"]
        enabled_widget = nested.widgets["enabled"]
        enabled_label = nested.labels["enabled"]
        enabled_reset = nested.reset_buttons["enabled"]

        retained_source_rows = [
            row
            for row in container.findChildren(ResponsiveParameterRow)
            if any(
                widget in (enabled_widget, enabled_label, enabled_reset)
                for widget, _stretch in (*row._left_widgets, *row._right_widgets)
                )
            ]
        visible_empty_rows = [
            row
            for row in container.findChildren(ResponsiveParameterRow)
            if row.isVisibleTo(manager)
            and row._row1_layout.count() == 0
            and row._row2_layout.count() == 0
        ]

        assert container.title_layout.isAncestorOf(enabled_widget)
        assert container.title_layout.isAncestorOf(enabled_reset)
        assert enabled_widget.isVisibleTo(manager)
        assert enabled_label.isHidden()
        assert nested.labels["enabled"] is enabled_label
        assert enabled_label.parentWidget() is None
        assert not sip.isdeleted(enabled_label)
        assert not sip.isdeleted(enabled_widget)
        assert not sip.isdeleted(enabled_reset)
        assert not retained_source_rows
        assert not visible_empty_rows

        nested.chrome_sync.update_label_styling("enabled")
        enabled_reset.click()
        qapp.processEvents()
        assert container.title_layout.isAncestorOf(enabled_widget)
        assert container.title_layout.isAncestorOf(enabled_reset)
    finally:
        manager.close()
        manager.deleteLater()
        ObjectStateRegistry.clear()
