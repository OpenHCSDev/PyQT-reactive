"""Notices in their role's colour: a line that keeps one until it is replaced, and the
application's status line, which puts each away when its seconds pass."""

from PySide6.QtCore import QTimer

from pyqt_reactive.theming import ColorScheme, StatusColorRole
from pyqt_reactive.widgets.fitted_text import WrappedText


class NoticeLine(WrappedText):
    """One notice, coloured by its StatusColorRole, kept until the next replaces it, wrapped
    inside whatever width it is given. A form row holds an editor's refusal here for as long
    as the editor holds the refused text."""

    def __init__(self, color_scheme: ColorScheme) -> None:
        super().__init__()
        self.color_scheme = color_scheme
        self.setContentsMargins(8, 4, 8, 4)
        self.hide()

    def show_status(self, text: str, role: StatusColorRole) -> None:
        self.setText(text)
        self.setStyleSheet(f"color: {role.color_hex(self.color_scheme)};")
        self.show()


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
