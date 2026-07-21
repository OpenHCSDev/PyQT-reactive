"""Vertical scroll area whose content width is owned by its viewport."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QScrollArea, QSizePolicy, QWidget


class ReflowingVerticalScrollArea(QScrollArea):
    """Keep content inside the horizontal viewport while scrolling vertically.

    ``QScrollArea.setWidgetResizable(True)`` still preserves a child's horizontal
    minimum-size hint by default. When horizontal scrolling is disabled, that can
    leave the child wider than the viewport after a vertical scrollbar appears.
    Declaring the horizontal size hint ignored makes the viewport the width owner;
    child layouts can then reflow without extending beneath the scrollbar.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def setWidget(self, widget: QWidget) -> None:  # noqa: N802
        """Attach content with a viewport-owned horizontal size policy."""

        size_policy = widget.sizePolicy()
        widget.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            size_policy.verticalPolicy(),
        )
        super().setWidget(widget)
