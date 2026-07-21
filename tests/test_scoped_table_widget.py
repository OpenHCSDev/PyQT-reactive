"""Regression tests for scope-aware table widgets."""

from __future__ import annotations

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QImage, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QWidget

from pyqt_reactive.forms.widget_strategies import PyQt6WidgetEnhancer
from pyqt_reactive.protocols import (
    ChangeSignalEmitter,
    PyQtWidgetMeta,
    ValueGettable,
    ValueSettable,
)
from pyqt_reactive.widgets.shared.clickable_help_components import (
    GroupBoxWithHelp,
    InlineDataclassGroupBox,
)
from pyqt_reactive.widgets.shared.scope_color_receiver import ScopeColorSchemeReceiver
from pyqt_reactive.widgets.shared.scope_visual_config import ScopeColorScheme
from pyqt_reactive.widgets.shared.scoped_table_widget import ScopedTableWidget


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


def test_scoped_table_overlay_clears_retained_pixels_before_repaint(qapp) -> None:
    table = ScopedTableWidget(1, 1)
    table.set_scope_color_scheme(_scope_scheme())
    table.resize(80, 40)
    table.show()
    qapp.processEvents()

    image = QImage(table._border_overlay.size(), QImage.Format.Format_ARGB32)
    image.fill(0)
    retained_line_y = image.height() // 2
    painter = QPainter(image)
    painter.setPen(QPen(QColor(40, 90, 120), 3))
    painter.drawLine(0, retained_line_y, image.width() - 1, retained_line_y)
    painter.end()

    table._border_overlay.render(image)

    assert image.pixelColor(image.width() // 2, retained_line_y).alpha() == 0


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


def test_inline_dataclass_groupbox_clears_placeholder_on_inline_change(qapp) -> None:
    class InlineValueWidget(
        QWidget,
        ValueGettable,
        ValueSettable,
        ChangeSignalEmitter,
        metaclass=PyQtWidgetMeta,
    ):
        def __init__(self) -> None:
            super().__init__()
            self.value = None
            self.callbacks = []

        def get_value(self):
            return self.value

        def set_value(self, value) -> None:
            self.value = value

        def connect_change_signal(self, callback) -> None:
            self.callbacks.append(callback)

        def disconnect_change_signal(self, callback) -> None:
            self.callbacks.remove(callback)

        def emit_value(self, value) -> None:
            self.value = value
            for callback in tuple(self.callbacks):
                callback(value)

    groupbox = InlineDataclassGroupBox(title="Inline")
    inline_widget = InlineValueWidget()
    emitted = []

    groupbox.set_value_widget(inline_widget)
    groupbox.mark_placeholder_state()
    groupbox.set_cached_placeholder_text("Pipeline default: inherited")

    PyQt6WidgetEnhancer.connect_change_signal(
        groupbox,
        "source_bindings",
        lambda name, value: emitted.append((name, value)),
    )
    inline_widget.emit_value("explicit")

    assert emitted == [("source_bindings", "explicit")]
    assert not groupbox.has_placeholder_state()


def test_groupbox_with_help_paints_extracted_scope_border(qapp) -> None:
    groupbox = GroupBoxWithHelp(title="Scoped")
    groupbox.set_scope_color_scheme(_scope_scheme())
    groupbox.resize(120, 80)

    groupbox.paintEvent(QPaintEvent(QRect(0, 0, 120, 80)))
