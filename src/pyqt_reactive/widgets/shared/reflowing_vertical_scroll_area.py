"""Vertical scroll area whose content width is owned by its viewport."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QMargins, QPoint, QRect, Qt, QTimer
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

        self._base_viewport_margins = QMargins()
        self._overlay_margin_left = 0
        self._overlay_margin_right = 0
        self._overlay_margin_timer = QTimer(self)
        self._overlay_margin_timer.setSingleShot(True)
        self._overlay_margin_timer.timeout.connect(self._sync_overlay_scrollbar_margin)

        vertical_bar = self.verticalScrollBar()
        vertical_bar.installEventFilter(self)
        vertical_bar.rangeChanged.connect(self._schedule_overlay_margin_sync)

    def setWidget(self, widget: QWidget) -> None:  # noqa: N802
        """Attach content with a viewport-owned horizontal size policy."""

        size_policy = widget.sizePolicy()
        widget.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            size_policy.verticalPolicy(),
        )
        super().setWidget(widget)
        self._schedule_overlay_margin_sync()

    def setViewportMargins(self, *args) -> None:  # noqa: N802
        """Preserve caller margins separately from the overlay reservation."""

        if len(args) == 1 and isinstance(args[0], QMargins):
            margins = QMargins(args[0])
        elif len(args) == 4 and all(isinstance(value, int) for value in args):
            margins = QMargins(*args)
        else:
            raise TypeError("setViewportMargins expects QMargins or four integers")

        self._base_viewport_margins = margins
        self._apply_viewport_margins()
        self._schedule_overlay_margin_sync()

    def eventFilter(self, watched, event):  # noqa: N802
        """Resynchronize when Qt moves or resizes the owned vertical bar."""

        if watched is self.verticalScrollBar() and event.type() in {
            QEvent.Type.Hide,
            QEvent.Type.Move,
            QEvent.Type.Resize,
            QEvent.Type.Show,
        }:
            self._schedule_overlay_margin_sync()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        """Re-evaluate containment after the scroll area is resized."""

        super().resizeEvent(event)
        self._schedule_overlay_margin_sync()

    def showEvent(self, event) -> None:  # noqa: N802
        """Defer the first containment pass until Qt has placed the viewport."""

        super().showEvent(event)
        self._schedule_overlay_margin_sync()

    def _schedule_overlay_margin_sync(self, *_args) -> None:
        """Coalesce geometry changes into the next layout turn."""

        self._overlay_margin_timer.start(0)

    def _sync_overlay_scrollbar_margin(self) -> None:
        """Reserve only the space that Qt's live scrollbar overlays.

        Native non-overlay scrollbars already reduce the viewport and therefore
        produce no intersection.  For an overlay scrollbar, expanding the live
        viewport by this class's current reservation reconstructs the viewport
        Qt would have supplied without our correction.  Its intersection with
        the live bar is the exact reservation needed, and keeps the calculation
        stable after that reservation has been applied.
        """

        vertical_bar = self.verticalScrollBar()
        target_left = 0
        target_right = 0
        if vertical_bar.maximum() > vertical_bar.minimum():
            viewport = self.viewport()
            viewport_rect = QRect(viewport.mapTo(self, QPoint()), viewport.size())
            unreserved_viewport_rect = viewport_rect.adjusted(
                -(self._base_viewport_margins.left() + self._overlay_margin_left),
                -self._base_viewport_margins.top(),
                self._base_viewport_margins.right() + self._overlay_margin_right,
                self._base_viewport_margins.bottom(),
            )
            bar_rect = QRect(
                vertical_bar.mapTo(self, QPoint()),
                vertical_bar.size(),
            )
            overlap = unreserved_viewport_rect.intersected(bar_rect)
            if not overlap.isEmpty():
                if bar_rect.center().x() < unreserved_viewport_rect.center().x():
                    target_left = overlap.width()
                else:
                    target_right = overlap.width()

        if target_left == self._overlay_margin_left and target_right == self._overlay_margin_right:
            return

        self._overlay_margin_left = target_left
        self._overlay_margin_right = target_right
        self._apply_viewport_margins()

    def _apply_viewport_margins(self) -> None:
        """Apply caller-owned margins plus this class's overlay correction."""

        super().setViewportMargins(
            self._base_viewport_margins.left() + self._overlay_margin_left,
            self._base_viewport_margins.top(),
            self._base_viewport_margins.right() + self._overlay_margin_right,
            self._base_viewport_margins.bottom(),
        )
