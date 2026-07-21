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

from pyqt_reactive.widgets.shared.abstract_table_browser import (
    ColumnDef,
    ColumnPresentationState,
)
from pyqt_reactive.widgets.shared.column_filter_widget import MultiColumnFilterPanel
from pyqt_reactive.widgets.shared.reflowing_vertical_scroll_area import (
    ReflowingVerticalScrollArea,
)


def _rect_in(widget: QWidget, owner: QWidget) -> QRect:
    return QRect(widget.mapTo(owner, widget.rect().topLeft()), widget.size())


def _contents_rect_in(widget: QWidget, owner: QWidget) -> QRect:
    contents_rect = widget.contentsRect()
    return QRect(
        widget.mapTo(owner, contents_rect.topLeft()),
        contents_rect.size(),
    )


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
        for width, height, vertical_scroll_required in (
            (500, 2000, False),
            (220, 160, True),
            (500, 2000, False),
            (100, 160, True),
        ):
            scroll_area.resize(width, height)
            _settle()

            viewport_rect = _rect_in(scroll_area.viewport(), scroll_area)
            content_rect = _rect_in(content, scroll_area)
            vertical_bar = scroll_area.verticalScrollBar()

            assert (vertical_bar.maximum() > vertical_bar.minimum()) is vertical_scroll_required
            assert content_rect.left() == viewport_rect.left()
            assert content_rect.width() == viewport_rect.width()
            representative_reset_rect = _rect_in(reset_buttons[0], scroll_area)
            assert viewport_rect.contains(representative_reset_rect)
            if vertical_scroll_required:
                vertical_bar_rect = _rect_in(vertical_bar, scroll_area)
                assert not viewport_rect.intersects(vertical_bar_rect)
                assert not representative_reset_rect.intersects(vertical_bar_rect)
                occupied_rect = viewport_rect.united(vertical_bar_rect)
                assert occupied_rect.left() == scroll_area.contentsRect().left()
                assert occupied_rect.right() == scroll_area.contentsRect().right()
            else:
                assert viewport_rect.left() == scroll_area.contentsRect().left()
                assert viewport_rect.right() == scroll_area.contentsRect().right()
    finally:
        scroll_area.close()


def test_reflowing_vertical_scroll_area_preserves_base_margins_stably(qapp) -> None:
    content = QWidget()
    content_layout = QVBoxLayout(content)
    for index in range(30):
        content_layout.addWidget(QLabel(f"row {index}", content))

    scroll_area = ReflowingVerticalScrollArea()
    base_margins = (3, 4, 7, 6)
    scroll_area.setViewportMargins(*base_margins)
    scroll_area.setWidget(content)
    scroll_area.resize(300, 180)
    scroll_area.show()

    try:
        _settle()
        vertical_bar = scroll_area.verticalScrollBar()
        assert vertical_bar.maximum() > vertical_bar.minimum()
        assert not _rect_in(scroll_area.viewport(), scroll_area).intersects(
            _rect_in(vertical_bar, scroll_area)
        )

        effective_margins = scroll_area.viewportMargins()
        assert effective_margins.left() >= base_margins[0]
        assert effective_margins.top() == base_margins[1]
        assert effective_margins.right() >= base_margins[2]
        assert effective_margins.bottom() == base_margins[3]
        compact_snapshot = (
            effective_margins,
            _rect_in(scroll_area.viewport(), scroll_area),
        )
        for _ in range(4):
            qapp.processEvents()
        assert (
            scroll_area.viewportMargins(),
            _rect_in(scroll_area.viewport(), scroll_area),
        ) == compact_snapshot

        scroll_area.resize(300, 2000)
        _settle()
        expanded_margins = scroll_area.viewportMargins()
        assert (
            expanded_margins.left(),
            expanded_margins.top(),
            expanded_margins.right(),
            expanded_margins.bottom(),
        ) == base_margins

        scroll_area.resize(300, 180)
        _settle()
        assert (
            scroll_area.viewportMargins(),
            _rect_in(scroll_area.viewport(), scroll_area),
        ) == compact_snapshot
    finally:
        scroll_area.close()


def test_column_filter_scrollbars_preserve_outer_width_and_long_value_access(
    qapp,
) -> None:
    presentation = ColumnPresentationState()
    columns = (
        ColumnDef("Extension", "extension"),
        ColumnDef("Channel", "channel"),
        ColumnDef("Full Virtual", "full_virtual"),
    )
    presentation.set_columns(columns)
    panel = MultiColumnFilterPanel(column_presentation=presentation)
    panel.add_column_filter(columns[0], [".tif"])
    panel.add_column_filter(columns[1], ["1 | W1", "2 | W2"])
    panel.add_column_filter(
        columns[2],
        [f"/tmp/openhcs_synthetic/plate/very-long-file-name-{index}.tif" for index in range(100)],
    )
    panel.show()

    try:
        for width, height, compact_viewport in (
            (300, 2000, False),
            (150, 600, True),
            (300, 2000, False),
            (130, 300, True),
        ):
            panel.resize(width, height)
            _settle()

            outer = panel.scroll_area
            outer_viewport_rect = _rect_in(outer.viewport(), panel)
            vertical_bar = outer.verticalScrollBar()
            vertical_scroll_required = vertical_bar.maximum() > vertical_bar.minimum()
            if compact_viewport:
                assert vertical_scroll_required
            assert panel.splitter.width() == outer.viewport().width()
            if vertical_scroll_required:
                vertical_bar_rect = _rect_in(vertical_bar, panel)
                assert not outer_viewport_rect.intersects(vertical_bar_rect)
                occupied_rect = outer_viewport_rect.united(vertical_bar_rect)
                outer_contents_rect = _contents_rect_in(outer, panel)
                assert occupied_rect.left() == outer_contents_rect.left()
                assert occupied_rect.right() == outer_contents_rect.right()

        long_value_filter = panel.column_filters["full_virtual"]
        inner = long_value_filter.findChild(QScrollArea)
        assert inner is not None
        assert inner.horizontalScrollBar().isVisible()
        assert inner.widget().width() > inner.viewport().width()
        assert not _rect_in(inner.viewport(), long_value_filter).intersects(
            _rect_in(inner.horizontalScrollBar(), long_value_filter)
        )
    finally:
        panel.close()
