"""One line of application status in its role's colour."""

from PySide6.QtWidgets import QLabel

from pyqt_reactive.theming import ColorScheme, StatusColorRole


class StatusLine(QLabel):
    """The latest notice, coloured by its StatusColorRole; the next one replaces it and a tap
    puts it away. Unlike a message box it runs no nested event loop, so it is safe on an
    application whose asyncio loop runs on Qt's (qasync), where a modal box stalls every
    task until it closes."""

    def __init__(self, color_scheme: ColorScheme) -> None:
        super().__init__()
        self.color_scheme = color_scheme
        self.setWordWrap(True)
        self.hide()

    def show_status(self, text: str, role: StatusColorRole) -> None:
        self.setText(text)
        self.setToolTip(text)
        self.setStyleSheet(f"color: {role.color_hex(self.color_scheme)}; padding: 4px 8px;")
        self.show()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt virtual method name
        self.hide()
        super().mousePressEvent(event)
