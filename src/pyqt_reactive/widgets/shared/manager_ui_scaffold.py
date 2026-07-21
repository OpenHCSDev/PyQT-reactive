"""Shared UI scaffold helpers for manager-like widgets."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from pyqt_reactive.core import ReorderableListWidget
from pyqt_reactive.widgets.shared.button_panel import ButtonPanel
from pyqt_reactive.widgets.shared.list_item_delegate import MultilinePreviewItemDelegate
from pyqt_reactive.widgets.shared.responsive_groupbox_title import (
    ResponsiveGroupBoxTitle,
)

MANAGER_STATUS_MINIMUM_VISIBLE_CHARACTERS = 28


@dataclass(frozen=True)
class ManagerHeaderParts:
    """Container returned by create_manager_header."""

    header: QWidget
    title_layout: ResponsiveGroupBoxTitle
    status_label: QLabel
    status_scroll: QScrollArea | None


@dataclass(frozen=True)
class ManagerWidgetUiParts:
    """Widgets created for a standard manager list UI."""

    header: QWidget
    title_layout: ResponsiveGroupBoxTitle
    status_label: QLabel
    status_scroll: QScrollArea | None
    item_list: ReorderableListWidget
    button_panel: ButtonPanel


def create_manager_header(
    *,
    title: str,
    color_scheme,
    enable_status_scrolling: bool = False,
) -> ManagerHeaderParts:
    """Create a standard manager header (title + status label)."""
    header = QWidget()
    header_layout = QHBoxLayout(header)
    header_layout.setContentsMargins(5, 5, 5, 5)

    title_label = QLabel(title)
    title_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
    title_label.setStyleSheet(
        f"color: {color_scheme.to_hex(color_scheme.text_accent)};"
    )
    title_layout = ResponsiveGroupBoxTitle(parent=header)
    title_layout.set_title_widget(title_label)
    header_layout.addWidget(title_layout, 1)

    if enable_status_scrolling:
        status_scroll = QScrollArea()
        status_scroll.setWidgetResizable(False)
        status_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        status_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        status_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        status_scroll.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        )
        status_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        status_scroll.setFixedHeight(20)
        status_scroll.setContentsMargins(0, 0, 0, 0)
        status_scroll.setStyleSheet(
            "QScrollArea { padding: 0px; margin: 0px; background: transparent; }"
        )

        status_label = QLabel("Ready")
        status_label.setStyleSheet(
            f"color: {color_scheme.to_hex(color_scheme.status_success)}; "
            "font-weight: bold; padding: 0px; margin: 0px;"
        )
        status_label.setTextFormat(Qt.TextFormat.PlainText)
        status_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        status_label.setFixedHeight(20)
        status_label.setContentsMargins(0, 0, 0, 0)
        status_label.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        )
        status_scroll.setMinimumWidth(
            status_label.fontMetrics().averageCharWidth()
            * MANAGER_STATUS_MINIMUM_VISIBLE_CHARACTERS
        )

        status_scroll.setWidget(status_label)
        title_layout.add_right_widget(status_scroll, 1)
        QTimer.singleShot(0, status_label.adjustSize)

        return ManagerHeaderParts(
            header=header,
            title_layout=title_layout,
            status_label=status_label,
            status_scroll=status_scroll,
        )

    status_label = QLabel("Ready")
    status_label.setStyleSheet(
        f"color: {color_scheme.to_hex(color_scheme.status_success)}; "
        "font-weight: bold;"
    )
    title_layout.add_right_widget(status_label)
    return ManagerHeaderParts(
        header=header,
        title_layout=title_layout,
        status_label=status_label,
        status_scroll=None,
    )


def create_manager_list_widget(
    *,
    color_scheme,
    style_generator,
    delegate_manager,
) -> ReorderableListWidget:
    """Create a styled manager list widget with the multiline preview delegate."""
    list_widget = ReorderableListWidget()
    list_widget.setStyleSheet(style_generator.generate_list_widget_style())

    delegate = MultilinePreviewItemDelegate(
        name_color=color_scheme.to_qcolor(color_scheme.text_primary),
        preview_color=color_scheme.to_qcolor(color_scheme.text_secondary),
        selected_text_color=color_scheme.to_qcolor(color_scheme.selection_text),
        parent=list_widget,
        manager=delegate_manager,
    )
    list_widget.setItemDelegate(delegate)
    return list_widget


def setup_manager_widget_ui(
    *,
    owner: QWidget,
    title: str,
    color_scheme,
    style_generator,
    enable_status_scrolling: bool,
    button_configs,
    on_action,
    button_grid_columns: int,
) -> ManagerWidgetUiParts:
    """Create and lay out the standard manager header, list, and button panel."""
    header_parts = create_manager_header(
        title=title,
        color_scheme=color_scheme,
        enable_status_scrolling=enable_status_scrolling,
    )
    item_list = create_manager_list_widget(
        color_scheme=color_scheme,
        style_generator=style_generator,
        delegate_manager=owner,
    )
    button_panel = ButtonPanel(
        button_configs=button_configs,
        on_action=on_action,
        style_generator=style_generator,
        grid_columns=button_grid_columns,
        parent=owner,
    )
    setup_vertical_manager_layout(
        owner=owner,
        header=header_parts.header,
        top_widget=item_list,
        bottom_widget=button_panel,
    )
    return ManagerWidgetUiParts(
        header=header_parts.header,
        title_layout=header_parts.title_layout,
        status_label=header_parts.status_label,
        status_scroll=header_parts.status_scroll,
        item_list=item_list,
        button_panel=button_panel,
    )


def setup_vertical_manager_layout(
    *,
    owner: QWidget,
    header: QWidget,
    top_widget: QWidget,
    bottom_widget: QWidget,
    margins: tuple[int, int, int, int] = (2, 2, 2, 2),
    spacing: int = 2,
    initial_sizes: tuple[int, int] = (1000, 1),
    stretch_factors: tuple[int, int] = (1, 0),
) -> QSplitter:
    """Create standard manager layout: header + vertical splitter."""
    main_layout = QVBoxLayout(owner)
    main_layout.setContentsMargins(*margins)
    main_layout.setSpacing(spacing)
    main_layout.addWidget(header)

    splitter = QSplitter(Qt.Orientation.Vertical)
    splitter.addWidget(top_widget)
    splitter.addWidget(bottom_widget)
    splitter.setSizes([initial_sizes[0], initial_sizes[1]])
    splitter.setStretchFactor(0, stretch_factors[0])
    splitter.setStretchFactor(1, stretch_factors[1])

    main_layout.addWidget(splitter)
    return splitter
