"""Small chrome owners an application composes: the status line and touch scrolling."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QListWidget, QScroller, QVBoxLayout, QWidget

from pyqt_reactive.theming import ColorScheme, StatusColorRole
from pyqt_reactive.widgets.shared.touch_scrolled import TouchScrolled
from pyqt_reactive.widgets.fitted_text import ElidedLine, WrappedText
from pyqt_reactive.widgets.status_line import StatusLine


def test_status_line_shows_the_latest_notice_in_its_role_colour_until_tapped(qapp) -> None:
    scheme = ColorScheme()
    line = StatusLine(scheme, 60)
    assert not line.isVisible()
    line.show_status("saved", StatusColorRole.SUCCESS)
    line.show_status("disk full", StatusColorRole.ERROR)
    assert line.isVisible() and line.text() == "disk full"
    assert StatusColorRole.ERROR.color_hex(scheme) in line.styleSheet()
    QTest.mouseClick(line, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    assert not line.isVisible()


def test_status_line_puts_a_notice_away_once_its_seconds_pass(qapp) -> None:
    line = StatusLine(ColorScheme(), 0.05)
    line.show_status("bus closed", StatusColorRole.ERROR)
    assert line.isVisible()
    QTest.qWait(300)
    assert not line.isVisible()


def test_a_later_notice_starts_the_time_again(qapp) -> None:
    line = StatusLine(ColorScheme(), 0.2)
    line.show_status("bus closed", StatusColorRole.ERROR)
    QTest.qWait(150)
    line.show_status("bus back", StatusColorRole.INFO)
    QTest.qWait(100)
    assert line.isVisible() and line.text() == "bus back"
    QTest.qWait(250)
    assert not line.isVisible()


def test_a_long_word_wraps_inside_a_phone_width(qapp) -> None:
    """One unbroken URL wider than the screen still wraps: the line never asks for more width
    than the window has, and its text fits the width it got."""
    line = StatusLine(ColorScheme(), 60)
    url = "https://example.invalid/" + "0123456789abcdef" * 8
    line.show_status(f"The comms observation at {url} closed", StatusColorRole.ERROR)
    window = QWidget()
    QVBoxLayout(window).addWidget(line)
    window.resize(412, 400)
    window.show()
    qapp.processEvents()
    assert window.width() == 412
    assert line.width() <= 412
    assert line.text_rect(line.width()).width() <= line.contentsRect().width()
    assert line.height() >= line.heightForWidth(line.width())


def test_a_long_elided_line_does_not_widen_a_phone_window(qapp) -> None:
    """A line longer than the screen takes the width it is given and ends in an ellipsis; the
    window stays at the phone's width."""
    text = "7 active · " + ", ".join(f"teammate-{index:02d}" for index in range(20))
    line = ElidedLine(text)
    window = QWidget()
    QVBoxLayout(window).addWidget(line)
    window.resize(412, 200)
    window.show()
    qapp.processEvents()
    assert line.sizeHint().width() > 412
    assert window.width() == 412 and line.width() <= 412
    assert line.toolTip() == text


def test_a_600_character_word_wraps_inside_a_phone_window(qapp) -> None:
    text = "k" * 600
    wrapped = WrappedText(text)
    window = QWidget()
    QVBoxLayout(window).addWidget(wrapped)
    window.resize(412, 600)
    window.show()
    qapp.processEvents()
    assert window.width() == 412 and wrapped.width() <= 412
    assert wrapped.text_rect(wrapped.width()).width() <= wrapped.contentsRect().width()
    assert wrapped.height() >= wrapped.heightForWidth(wrapped.width()) and wrapped.toolTip() == text


def test_touch_scrolled_area_holds_a_kinetic_scroller(qapp) -> None:
    class TouchList(TouchScrolled, QListWidget):
        """A list a finger scrolls."""

    rows = TouchList()
    assert QScroller.hasScroller(rows.viewport())
