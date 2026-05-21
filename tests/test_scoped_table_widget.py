"""Regression tests for scope-aware table widgets."""

from __future__ import annotations

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QImage, QPaintEvent
from pyqt_reactive.widgets.shared.clickable_help_components import (
    GroupBoxWithHelp,
    InlineDataclassGroupBox,
)
from pyqt_reactive.widgets.shared.scope_color_receiver import ScopeColorSchemeReceiver
from pyqt_reactive.widgets.shared.scoped_table_widget import ScopedTableWidget
from pyqt_reactive.widgets.shared.scope_visual_config import ScopeColorScheme


def _scope_scheme() -> ScopeColorScheme:
    return ScopeColorScheme(
        scope_id="plate::step_0",
        hue=0,
        orchestrator_item_bg_rgb=(40, 90, 120),
        orchestrator_item_border_rgb=(40, 90, 120),
        step_window_border_rgb=(40, 90, 120),
        step_item_bg_rgb=(40, 90, 120),
        step_border_layers=[(3, 0, "dashed"), (3, 1, "dotted")],
        base_color_rgb=(40, 90, 120),
    )


def test_scoped_table_widget_accepts_scope_scheme_and_paints(qapp) -> None:
    table = ScopedTableWidget(1, 1)
    scheme = _scope_scheme()

    table.set_scope_color_scheme(scheme)
    table.resize(80, 40)
    table.show()
    qapp.processEvents()

    assert table._scope_color_scheme is scheme
    assert table._border_overlay.isVisible()
    assert "border: 6px solid transparent" in table.styleSheet()

    image = QImage(table.size(), QImage.Format.Format_ARGB32)
    image.fill(0)
    table.render(image)
    border_pixel = image.pixelColor(1, 1)
    assert border_pixel.alpha() > 0
    assert border_pixel != image.pixelColor(20, 20)

    table.set_scope_color_scheme(None)
    assert not table._border_overlay.isVisible()


def test_inline_dataclass_groupbox_propagates_scope_to_inline_widget(qapp) -> None:
    class InlineWidget(ScopeColorSchemeReceiver):
        def __init__(self) -> None:
            self.scope_scheme = None

        def set_scope_color_scheme(self, scheme) -> None:
            self.scope_scheme = scheme

    groupbox = InlineDataclassGroupBox(title="Inline")
    inline_widget = InlineWidget()
    scheme = _scope_scheme()

    groupbox.set_scope_color_scheme(scheme)
    groupbox.set_value_widget(inline_widget)

    assert inline_widget.scope_scheme is scheme


def test_groupbox_with_help_paints_extracted_scope_border(qapp) -> None:
    groupbox = GroupBoxWithHelp(title="Scoped")
    groupbox.set_scope_color_scheme(_scope_scheme())
    groupbox.resize(120, 80)

    groupbox.paintEvent(QPaintEvent(QRect(0, 0, 120, 80)))
