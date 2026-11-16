"""Text that fits whatever width its layout gives it.

A QLabel will not go narrower than its longest unbreakable run of text, so one long line (a
list of active teammates, a URL in an error, a thread status) set a minimum width on every
ancestor up to the window, and on a phone the window then ran past the screen. FittedText
asks for its text's width but needs only its margins; each member decides how text that
does not fit is shown, and the whole text stays the tooltip."""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import QLabel


class FittedText(QLabel):
    """Text that takes the width it is given; members draw what does not fit."""

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt method name
        super().setText(text)
        self.setToolTip(text)
        self.updateGeometry()

    def drawn(self, rect: QRect) -> tuple[int, str]:
        """The text flags and the text painted into this rectangle."""
        raise NotImplementedError

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method name
        margins = self.contentsMargins()
        return QSize(margins.left() + margins.right(),
                     self.fontMetrics().height() + margins.top() + margins.bottom())

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt virtual method name
        rect = self.contentsRect()
        flags, text = self.drawn(rect)
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        painter.drawText(rect, flags, text)


class ElidedLine(FittedText):
    """One line; what does not fit ends in an ellipsis."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setWordWrap(False)

    def drawn(self, rect: QRect) -> tuple[int, str]:
        return int(self.alignment()), self.fontMetrics().elidedText(
            self.text(), Qt.TextElideMode.ElideRight, rect.width())


class WrappedText(FittedText):
    """Lines that wrap at words, breaking a word only when it alone is wider than the line,
    and as tall as the wrapped text needs at the width given."""

    WRAP = Qt.TextFlag.TextWordWrap | Qt.TextFlag.TextWrapAnywhere

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setWordWrap(True)

    def text_rect(self, width: int) -> QRect:
        margins = self.contentsMargins()
        inner = max(width - margins.left() - margins.right(), 1)
        return self.fontMetrics().boundingRect(QRect(0, 0, inner, 1 << 20), int(self.WRAP), self.text())

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt virtual method name
        margins = self.contentsMargins()
        return self.text_rect(width).height() + margins.top() + margins.bottom()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method name
        margins = self.contentsMargins()
        width = self.fontMetrics().boundingRect(QRect(0, 0, 1 << 20, 1 << 20), 0, self.text()).width()
        width += margins.left() + margins.right()
        return QSize(width, self.heightForWidth(width))

    def drawn(self, rect: QRect) -> tuple[int, str]:
        return int(self.WRAP | self.alignment()), self.text()
