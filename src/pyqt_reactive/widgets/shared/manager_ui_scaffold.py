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


@dataclass(frozen=True)
class ManagerHeaderParts:
    """Container returned by create_manager_header."""

    header: QWidget
    status_label: QLabel
    status_scroll: QScrollArea | None


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
    header_layout.addWidget(title_label)

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

        status_scroll.setWidget(status_label)
        header_layout.addWidget(status_scroll, 1)
        QTimer.singleShot(0, status_label.adjustSize)

        return ManagerHeaderParts(
            header=header,
            status_label=status_label,
            status_scroll=status_scroll,
        )

    header_layout.addStretch()
    status_label = QLabel("Ready")
    status_label.setStyleSheet(
        f"color: {color_scheme.to_hex(color_scheme.status_success)}; "
        "font-weight: bold;"
    )
    header_layout.addWidget(status_label)
    return ManagerHeaderParts(
        header=header,
        status_label=status_label,
        status_scroll=None,
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
