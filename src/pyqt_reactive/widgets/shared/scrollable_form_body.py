"""Shared form body composition for tree-backed parameter editors."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QScrollArea, QSplitter, QWidget

from pyqt_reactive.core.collapsible_splitter_helper import CollapsibleSplitterHelper
from pyqt_reactive.widgets.shared.reflowing_vertical_scroll_area import (
    ReflowingVerticalScrollArea,
)


@dataclass(frozen=True)
class ScrollableFormBodyParts:
    """Widgets created for a scrollable form body."""

    body_widget: QWidget
    scroll_area: QScrollArea
    tree_widget: QWidget | None
    splitter: QSplitter | None
    splitter_helper: CollapsibleSplitterHelper | None


def create_scrollable_form_body(
    *,
    form_widget: QWidget,
    tree_widget: QWidget | None = None,
    tree_initial_size: int = 300,
    form_initial_size: int = 700,
    parent: QWidget | None = None,
) -> ScrollableFormBodyParts:
    """Create a scrollable form with an optional collapsible navigation tree."""
    scroll_area = ReflowingVerticalScrollArea(parent)
    scroll_area.setWidget(form_widget)

    if tree_widget is None:
        return ScrollableFormBodyParts(
            body_widget=scroll_area,
            scroll_area=scroll_area,
            tree_widget=None,
            splitter=None,
            splitter_helper=None,
        )

    splitter = QSplitter(Qt.Orientation.Horizontal, parent)
    splitter.setChildrenCollapsible(True)
    splitter.setHandleWidth(5)
    splitter.addWidget(tree_widget)
    splitter.addWidget(scroll_area)
    splitter.setSizes([tree_initial_size, form_initial_size])

    splitter_helper = CollapsibleSplitterHelper(splitter, left_panel_index=0)
    splitter_helper.set_initial_size(tree_initial_size)

    return ScrollableFormBodyParts(
        body_widget=splitter,
        scroll_area=scroll_area,
        tree_widget=tree_widget,
        splitter=splitter,
        splitter_helper=splitter_helper,
    )
