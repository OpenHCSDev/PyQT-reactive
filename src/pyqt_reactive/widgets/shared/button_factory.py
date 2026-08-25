from PyQt6.QtWidgets import QPushButton

from pyqt_reactive.services.scope_color_service import ScopeColorService
from pyqt_reactive.theming import AccentChromeColorPolicy


def make_accented_button(scope_id: str | None, text: str, callback=None, checkable: bool = False):
    """Create a QPushButton styled with the scope accent color.

    This central factory queries ScopeColorService for the accent color (which
    always returns a QColor) and unconditionally applies the accent stylesheet.
    """
    btn = QPushButton(text)
    if checkable:
        btn.setCheckable(True)
    if callback is not None:
        btn.clicked.connect(callback)

    chrome = AccentChromeColorPolicy.resolve(
        ScopeColorService.instance().get_accent_color(scope_id)
    )
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {chrome.background};
            color: {chrome.text};
            border: {chrome.border};
            border-radius: 3px;
            padding: 5px;
        }}
        QPushButton:hover {{
            background-color: {chrome.hover};
        }}
        QPushButton:pressed {{
            background-color: {chrome.pressed};
        }}
    """)

    return btn
