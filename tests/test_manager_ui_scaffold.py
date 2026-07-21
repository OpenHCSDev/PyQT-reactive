from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import QPushButton, QWidget

from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.shared.manager_ui_scaffold import (
    MANAGER_STATUS_MINIMUM_VISIBLE_CHARACTERS,
    create_manager_header,
)


def _rect_in(widget: QWidget, owner: QWidget) -> QRect:
    return QRect(widget.mapTo(owner, QPoint()), widget.size())


def _activate_header_layout(qapp, parts) -> None:
    """Resolve the nested responsive layouts without waiting on resize timers."""

    staged_layout = parts.title_layout._staged_layout
    for _ in range(2):
        qapp.processEvents()
        parts.header.layout().activate()
        parts.title_layout.layout().activate()
        staged_layout.refresh_layout()
        staged_layout.layout().activate()
        staged_layout._row1_layout.activate()
        staged_layout._row2_layout.activate()


@pytest.mark.parametrize("title", ("Plate Manager", "Pipeline Editor"))
@pytest.mark.parametrize("viewport_mode", ("compact", "intermediate", "full_text"))
def test_scrolling_manager_header_preserves_usable_status_viewport(
    qapp,
    title: str,
    viewport_mode: str,
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

    try:
        assert parts.status_scroll is not None
        minimum_viewport_width = (
            parts.status_label.fontMetrics().averageCharWidth()
            * MANAGER_STATUS_MINIMUM_VISIBLE_CHARACTERS
        )
        staged_layout = parts.title_layout._staged_layout
        title_width = parts.title_layout._title_group.sizeHint().width()
        layout_spacing = staged_layout._spacing
        header_margins = parts.header.layout().contentsMargins()
        header_margin_width = header_margins.left() + header_margins.right()
        compact_content_width = max(
            minimum_viewport_width,
            title_width + layout_spacing,
        )
        full_text_content_width = (
            title_width + parts.status_label.sizeHint().width() + 2 * layout_spacing
        )
        content_widths = {
            "compact": compact_content_width,
            "intermediate": (compact_content_width + full_text_content_width) // 2,
            "full_text": full_text_content_width,
        }
        header_width = content_widths[viewport_mode] + header_margin_width
        parts.header.resize(header_width, max(30, parts.header.sizeHint().height()))
        parts.header.show()
        _activate_header_layout(qapp, parts)

        assert parts.status_scroll.minimumWidth() == minimum_viewport_width
        assert parts.status_scroll.viewport().width() >= minimum_viewport_width

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
            row_layout.itemAt(index).spacerItem() is None for index in range(right_item_index)
        )
        right_group_rect = _rect_in(right_group, parts.header)
        row_rect = _rect_in(row_widget, parts.header)
        status_rect = _rect_in(parts.status_scroll, parts.header)
        assert right_group_rect.right() == row_rect.right()
        assert status_rect.left() == right_group_rect.left()
        assert status_rect.right() == right_group_rect.right()
        if viewport_mode != "compact":
            assert parts.status_scroll.width() > minimum_viewport_width

        if staged_layout._last_row2 == [parts.title_layout.RIGHT_GROUP]:
            assert right_group_rect.left() == row_rect.left()
        if viewport_mode == "full_text":
            assert parts.status_scroll.horizontalScrollBar().maximum() == 0
    finally:
        parts.header.close()
