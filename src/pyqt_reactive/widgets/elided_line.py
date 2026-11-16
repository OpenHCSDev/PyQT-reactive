"""One line of text that fits whatever width its layout gives it."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import QLabel


class ElidedLine(QLabel):
    """A single line that asks for its whole text's width but takes less: what does not fit
    ends in an ellipsis, and the whole text is the tooltip.

    A QLabel without word wrap will not go narrower than its text, so one long line (a list
    of active teammates, a thread status) set a minimum width on every ancestor up to the
    window, and on a phone the window then ran past the screen."""

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self.setWordWrap(False)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt method name
        super().setText(text)
        self.setToolTip(text)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method name
        margins = self.contentsMargins()
        return QSize(margins.left() + margins.right(), super().minimumSizeHint().height())

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt virtual method name
        rect = self.contentsRect()
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        shown = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, int(self.alignment()), shown)
