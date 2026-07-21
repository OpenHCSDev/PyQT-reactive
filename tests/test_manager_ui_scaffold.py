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
@pytest.mark.parametrize("header_width", (320, 500))
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
    finally:
        parts.header.close()
