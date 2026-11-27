"""Real Qt paint and cache invalidation tests for FittedText."""

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette

from pyqt_reactive.widgets.fitted_text import ElidedLine, WrappedText


def test_elided_line_caches_per_width_and_invalidates_on_text_font_palette_and_alignment(qtbot):
    widget = ElidedLine("a very long line that will certainly elide at narrow widths")
    qtbot.addWidget(widget)
    widget.resize(120, 28)
    widget.show()
    qtbot.waitExposed(widget)

    # First paint populates caches.
    first_rect = widget.contentsRect()
    flags, elided = widget.drawn(first_rect)
    assert elided.endswith("…") or elided.endswith("...")
    assert flags == int(widget.alignment())
    widget.grab()

    # Subsequent paint at same width/text/font/palette enters only paintEvent + drawn (no enum/elide churn).
    calls = []

    def trace(frame, event, _arg):
        if event == "call":
            calls.append(frame.f_code.co_qualname)

    sys.setprofile(trace)
    widget.grab()
    sys.setprofile(None)
    assert calls == ["FittedText.paintEvent", "ElidedLine.drawn"]

    # Resize updates cached elision.
    widget.resize(600, 28)
    _, wide = widget.drawn(widget.contentsRect())
    assert wide == widget.text()

    # Text change invalidates cached elision.
    widget.resize(120, 28)
    _, narrow = widget.drawn(widget.contentsRect())
    assert narrow != wide
    widget.setText("short")
    _, short = widget.drawn(widget.contentsRect())
    assert short == "short"

    # Font change invalidates cached elision.
    widget.setText("medium length text here")
    _, small_font = widget.drawn(widget.contentsRect())
    big = QFont(widget.font())
    big.setPointSize(24)
    widget.setFont(big)
    _, big_font = widget.drawn(widget.contentsRect())
    assert len(big_font) < len(small_font)

    # Alignment update updates cached flags.
    widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    flags, _ = widget.drawn(widget.contentsRect())
    assert flags == int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    # Palette change invalidates cached text color.
    palette = widget.palette()
    red = QColor(220, 20, 30)
    palette.setColor(QPalette.ColorRole.WindowText, red)
    widget.setPalette(palette)
    widget.grab()
    assert widget._text_color == red


def test_wrapped_text_updates_alignment_flags_and_measures_height(qtbot):
    widget = WrappedText("word " * 40)
    qtbot.addWidget(widget)
    widget.resize(120, 200)
    widget.show()
    widget.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
    flags, text = widget.drawn(widget.contentsRect())
    assert flags == int(WrappedText.WRAP | Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
    assert text == widget.text()
    first_height = widget.heightForWidth(120)
    assert first_height > widget.minimumSizeHint().height()
    assert not widget.grab().isNull()

    # Repeated heightForWidth(120) hits cache without recomputing text_rect.
    text_rect_calls = 0
    orig_text_rect = widget.text_rect

    def counting_text_rect(width: int):
        nonlocal text_rect_calls
        text_rect_calls += 1
        return orig_text_rect(width)

    widget.text_rect = counting_text_rect
    assert widget.heightForWidth(120) == first_height
    assert text_rect_calls == 0

    # Same text is a no-op (keeps cache warm and avoids layout churn).
    widget.setText("word " * 40)
    assert widget.heightForWidth(120) == first_height
    assert text_rect_calls == 0

    # Margin change invalidates heightForWidth and minimumSizeHint caches.
    widget.setContentsMargins(0, 10, 0, 10)
    taller = widget.heightForWidth(120)
    assert text_rect_calls == 1
    assert taller == first_height + 20

    # Font change invalidates heightForWidth cache.
    big = QFont(widget.font())
    big.setPointSize(24)
    widget.setFont(big)
    bigger = widget.heightForWidth(120)
    assert text_rect_calls == 2
    assert bigger > taller

    # Text change invalidates heightForWidth and sizeHint caches.
    widget.setText("short")
    shorter = widget.heightForWidth(120)
    assert text_rect_calls == 3
    assert shorter < bigger
    assert widget.sizeHint().height() <= bigger
