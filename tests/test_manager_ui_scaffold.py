from __future__ import annotations

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QPushButton

from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.shared.manager_ui_scaffold import (
    MANAGER_STATUS_MINIMUM_VISIBLE_CHARACTERS,
    create_manager_header,
)


@pytest.mark.parametrize("title", ("Plate Manager", "Pipeline Editor"))
@pytest.mark.parametrize("header_width", (320, 500, 800))
def test_scrolling_manager_header_preserves_usable_status_viewport(
    qapp,
    title: str,
    header_width: int,
) -> None:
    parts = create_manager_header(
        title=title,
        color_scheme=ColorScheme(),
        enable_status_scrolling=True,
    )
    parts.title_layout.set_help_widget(QPushButton("Help", parts.header))
    parts.status_label.setText(
        "3 plates | selected dataset initialized | pipeline ready to compile"
    )
    parts.status_label.adjustSize()
    parts.header.resize(header_width, max(30, parts.header.sizeHint().height()))
    parts.header.show()

    try:
        QTest.qWait(75)
        assert parts.status_scroll is not None
        minimum_viewport_width = (
            parts.status_label.fontMetrics().averageCharWidth()
            * MANAGER_STATUS_MINIMUM_VISIBLE_CHARACTERS
        )
        assert parts.status_scroll.minimumWidth() == minimum_viewport_width
        assert parts.status_scroll.viewport().width() >= minimum_viewport_width

        staged_layout = parts.title_layout._staged_layout
        right_group = parts.title_layout._right_group
        if parts.title_layout.RIGHT_GROUP in staged_layout._last_row1:
            row_widget = staged_layout._row1_widget
            row_layout = staged_layout._row1_layout
        else:
            row_widget = staged_layout._row2_widget
            row_layout = staged_layout._row2_layout

        right_item_index = next(
            index
            for index in range(row_layout.count())
            if row_layout.itemAt(index).widget() is right_group
        )
        assert row_layout.stretch(right_item_index) > 0
        assert all(
            row_layout.itemAt(index).spacerItem() is None
            for index in range(right_item_index)
        )
        assert right_group.geometry().right() == row_widget.contentsRect().right()
        assert parts.status_scroll.width() == right_group.contentsRect().width()
        assert parts.status_scroll.width() > minimum_viewport_width

        if staged_layout._last_row2 == [parts.title_layout.RIGHT_GROUP]:
            assert right_group.geometry().left() == row_widget.contentsRect().left()
        if header_width == 800:
            assert parts.status_scroll.horizontalScrollBar().maximum() == 0
    finally:
        parts.header.close()
