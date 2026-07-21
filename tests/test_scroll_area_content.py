from __future__ import annotations

from PyQt6.QtCore import QRect
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pyqt_reactive.widgets.shared.column_filter_widget import MultiColumnFilterPanel
from pyqt_reactive.widgets.shared.reflowing_vertical_scroll_area import (
    ReflowingVerticalScrollArea,
)


def _rect_in(widget: QWidget, owner: QWidget) -> QRect:
    return QRect(widget.mapTo(owner, widget.rect().topLeft()), widget.size())


def _settle() -> None:
    QTest.qWait(25)


def test_reflowing_vertical_scroll_area_tracks_viewport_width_across_bar_transitions(
    qapp,
) -> None:
    content = QWidget()
    content_layout = QVBoxLayout(content)
    reset_buttons: list[QPushButton] = []
    for _ in range(12):
        row = QWidget(content)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(QLabel("Persistent configuration value", row))
        reset_button = QPushButton("Reset", row)
        reset_buttons.append(reset_button)
        row_layout.addWidget(reset_button)
        content_layout.addWidget(row)

    scroll_area = ReflowingVerticalScrollArea()
    scroll_area.setWidget(content)
    scroll_area.show()

    try:
        for width, height, vertical_bar_visible in (
            (500, 500, False),
            (220, 160, True),
            (500, 500, False),
            (100, 160, True),
        ):
            scroll_area.resize(width, height)
            _settle()

            viewport_rect = _rect_in(scroll_area.viewport(), scroll_area)
            content_rect = _rect_in(content, scroll_area)
            vertical_bar = scroll_area.verticalScrollBar()

            assert vertical_bar.isVisible() is vertical_bar_visible
            assert content_rect.left() == viewport_rect.left()
            assert content_rect.width() == viewport_rect.width()
            representative_reset_rect = _rect_in(reset_buttons[0], scroll_area)
            assert viewport_rect.contains(representative_reset_rect)
            if vertical_bar_visible:
                vertical_bar_rect = _rect_in(vertical_bar, scroll_area)
                assert not viewport_rect.intersects(vertical_bar_rect)
                assert not representative_reset_rect.intersects(vertical_bar_rect)
    finally:
        scroll_area.close()


def test_column_filter_scrollbars_preserve_outer_width_and_long_value_access(
    qapp,
) -> None:
    panel = MultiColumnFilterPanel()
    panel.add_column_filter("Extension", [".tif"])
    panel.add_column_filter("Channel", ["1 | W1", "2 | W2"])
    panel.add_column_filter(
        "Full Virtual",
        [
            f"/tmp/openhcs_synthetic/plate/very-long-file-name-{index}.tif"
            for index in range(100)
        ],
    )
    panel.show()

    try:
        for width, height, vertical_bar_visible in (
            (300, 900, False),
            (150, 600, True),
            (300, 900, False),
            (130, 300, True),
        ):
            panel.resize(width, height)
            _settle()

            outer = panel.scroll_area
            outer_viewport_rect = _rect_in(outer.viewport(), panel)
            assert outer.verticalScrollBar().isVisible() is vertical_bar_visible
            assert panel.splitter.width() == outer.viewport().width()
            if vertical_bar_visible:
                assert not outer_viewport_rect.intersects(
                    _rect_in(outer.verticalScrollBar(), panel)
                )

        long_value_filter = panel.column_filters["Full Virtual"]
        inner = long_value_filter.findChild(QScrollArea)
        assert inner is not None
        assert inner.horizontalScrollBar().isVisible()
        assert inner.widget().width() > inner.viewport().width()
        assert not _rect_in(inner.viewport(), long_value_filter).intersects(
            _rect_in(inner.horizontalScrollBar(), long_value_filter)
        )
    finally:
        panel.close()
