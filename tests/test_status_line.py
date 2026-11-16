"""Small chrome owners an application composes: the status line and touch scrolling."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QListWidget, QScroller

from pyqt_reactive.theming import ColorScheme, StatusColorRole
from pyqt_reactive.widgets.shared.touch_scrolled import TouchScrolled
from pyqt_reactive.widgets.status_line import StatusLine


def test_status_line_shows_the_latest_notice_in_its_role_colour_until_tapped(qapp) -> None:
    scheme = ColorScheme()
    line = StatusLine(scheme)
    assert not line.isVisible()
    line.show_status("saved", StatusColorRole.SUCCESS)
    line.show_status("disk full", StatusColorRole.ERROR)
    assert line.isVisible() and line.text() == "disk full"
    assert StatusColorRole.ERROR.color_hex(scheme) in line.styleSheet()
    QTest.mouseClick(line, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    assert not line.isVisible()


def test_touch_scrolled_area_holds_a_kinetic_scroller(qapp) -> None:
    class TouchList(TouchScrolled, QListWidget):
        """A list a finger scrolls."""

    rows = TouchList()
    assert QScroller.hasScroller(rows.viewport())
