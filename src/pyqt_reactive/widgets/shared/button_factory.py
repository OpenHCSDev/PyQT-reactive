from typing import Optional
from PyQt6.QtWidgets import QPushButton


def make_accented_button(scope_id: Optional[str], text: str, callback=None, checkable: bool = False):
    """Create a QPushButton styled with the scope accent color.

    This central factory queries ScopeColorService for the accent color (which
    always returns a QColor) and unconditionally applies the accent stylesheet.
    """
    from pyqt_reactive.services.scope_color_service import ScopeColorService

    btn = QPushButton(text)
    if checkable:
        btn.setCheckable(True)
    if callback is not None:
        btn.clicked.connect(callback)

    svc = ScopeColorService.instance()
    accent = svc.get_accent_color(scope_id)

    # Apply accent style unconditionally (service returns QColor)
    try:
        hex_color = accent.name()
        lighter = accent.lighter(115).name()
        darker = accent.darker(115).name()
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {hex_color};
                color: white;
                border: none;
                border-radius: 3px;
                padding: 5px;
            }}
            QPushButton:hover {{
                background-color: {lighter};
            }}
            QPushButton:pressed {{
                background-color: {darker};
            }}
        """)
    except Exception:
        # If accent is somehow invalid, fall back to default appearance
        pass

    return btn
