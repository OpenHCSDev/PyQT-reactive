"""Regression tests for scoped border rendering."""

from __future__ import annotations

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QPaintEvent
from PyQt6.QtWidgets import QWidget

from pyqt_reactive.widgets.shared.scoped_border_mixin import ScopedBorderMixin


def test_scoped_border_mixin_paint_event_handles_mixin_first_mro(qapp) -> None:
    """Mixin-first widgets should not require a Qt paintEvent in super()."""
    scoped_border_widget_type = type(
        "ScopedBorderWidget",
        (ScopedBorderMixin, QWidget),
        {},
    )
    widget = scoped_border_widget_type()
    widget.resize(32, 32)

    widget.paintEvent(QPaintEvent(QRect(0, 0, 32, 32)))
