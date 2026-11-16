"""Notices in their role's colour: a line that keeps one until it is replaced, and the
application's status line, which puts each away when its seconds pass."""

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import QLabel

from pyqt_reactive.theming import ColorScheme, StatusColorRole


class NoticeLine(QLabel):
    """One notice, coloured by its StatusColorRole, kept until the next replaces it. A form
    row holds an editor's refusal here for as long as the editor holds the refused text.

    The text wraps inside whatever width the window gives it. QLabel's word wrap never breaks
    a word, so one long URL in an error made the label wider than a 412 px phone screen; this
    line wraps at words and breaks a word only when it alone is wider than the line."""

    WRAP = Qt.TextFlag.TextWordWrap | Qt.TextFlag.TextWrapAnywhere

    def __init__(self, color_scheme: ColorScheme) -> None:
        super().__init__()
        self.color_scheme = color_scheme
        self.setWordWrap(True)
        self.setContentsMargins(8, 4, 8, 4)
        self.hide()

    def show_status(self, text: str, role: StatusColorRole) -> None:
        self.setText(text)
        self.setToolTip(text)
        self.setStyleSheet(f"color: {role.color_hex(self.color_scheme)};")
        self.updateGeometry()
        self.show()

    def text_rect(self, width: int) -> QRect:
        margins = self.contentsMargins()
        inner = max(width - margins.left() - margins.right(), 1)
        return self.fontMetrics().boundingRect(QRect(0, 0, inner, 1 << 20), int(self.WRAP), self.text())

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt virtual method name
        margins = self.contentsMargins()
        return self.text_rect(width).height() + margins.top() + margins.bottom()

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method name
        margins = self.contentsMargins()
        return QSize(margins.left() + margins.right(),
                     self.fontMetrics().height() + margins.top() + margins.bottom())

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method name
        margins = self.contentsMargins()
        width = self.fontMetrics().boundingRect(QRect(0, 0, 1 << 20, 1 << 20), 0, self.text()).width()
        width += margins.left() + margins.right()
        return QSize(width, self.heightForWidth(width))

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt virtual method name
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        painter.drawText(self.contentsRect(), int(self.WRAP | Qt.AlignmentFlag.AlignLeft), self.text())


class StatusLine(NoticeLine):
    """The application's latest notice, shown for the line's notice seconds; the next one
    replaces it and starts its time again, and a tap puts it away sooner. Unlike a message box
    it runs no nested event loop, so it is safe on an application whose asyncio loop runs on
    Qt's (qasync), where a modal box stalls every task until it closes."""

    def __init__(self, color_scheme: ColorScheme, seconds: float) -> None:
        super().__init__(color_scheme)
        # One timer for the line, restarted by each notice, so an earlier notice's time never
        # puts away a later one.
        self.expiry = QTimer(self)
        self.expiry.setSingleShot(True)
        self.expiry.setInterval(int(seconds * 1000))
        self.expiry.timeout.connect(self.hide)

    def show_status(self, text: str, role: StatusColorRole) -> None:
        super().show_status(text, role)
        self.expiry.start()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt virtual method name
        self.expiry.stop()
        self.hide()
        super().mousePressEvent(event)
