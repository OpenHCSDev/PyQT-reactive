"""Kinetic finger scrolling for any Qt scroll area."""

from PySide6.QtWidgets import QScroller


class TouchScrolled:
    """Mixed in before a QAbstractScrollArea base: a finger drag scrolls the viewport
    kinetically. Qt widgets on Android scroll only by scroll bar unless a QScroller holds
    the viewport."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        QScroller.grabGesture(self.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
