"""Detachable action bar for widgets that can render actions externally."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QWidget


class DetachableActionBar(QWidget):
    """Right-aligned action buttons that can be embedded in another header."""

    def __init__(self, *, object_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignRight)

    def add_button(self, button: QPushButton) -> None:
        """Append a button to the action bar."""
        self._layout.addWidget(button)

    def external_widget(self, *, render_header: bool) -> QWidget | None:
        """Return the bar only when the owning widget did not render its header."""
        if render_header:
            return None
        return self


class DetachableActionBarHost:
    """Mixin for widgets that expose a detachable action bar."""

    _action_buttons_container: DetachableActionBar
    _render_header: bool

    def get_action_buttons(self) -> QWidget | None:
        """Return externally renderable actions when this widget owns no header."""
        return self._action_buttons_container.external_widget(
            render_header=self._render_header
        )
