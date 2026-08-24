"""Reusable status indicator widget with colored dot, label, and refresh button."""

from abc import ABCMeta
from collections.abc import Callable
from enum import Enum
from functools import partialmethod

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget
from zmqruntime.startup import EndpointStartupPresentationTarget

from pyqt_reactive.core import BackgroundTaskManager
from pyqt_reactive.theming import ColorScheme, StatusColorRole

# --- Module-level constants ---
DEFAULT_DEBOUNCE_MS = 2000  # Debounce for connection checks


class _CombinedMeta(ABCMeta, type(QWidget)):
    """Combine nominal presentation and Qt widget metaclasses."""


class StatusState(Enum):
    """Status indicator states whose colors come from the active theme."""

    def __new__(
        cls,
        value: str,
        default_message: str | None,
        color_role: StatusColorRole,
    ) -> "StatusState":
        member = object.__new__(cls)
        member._value_ = value
        member.default_message = default_message
        member.color_role = color_role
        return member

    UNKNOWN = ("Unknown", "Unknown", StatusColorRole.UNKNOWN)
    CHECKING = ("Checking...", "Checking...", StatusColorRole.WARNING)
    CONNECTED = ("connected", None, StatusColorRole.SUCCESS)
    DISCONNECTED = ("disconnected", None, StatusColorRole.ERROR)
    WARNING = ("warning", None, StatusColorRole.WARNING)


class StatusIndicator(
    QWidget,
    EndpointStartupPresentationTarget,
    metaclass=_CombinedMeta,
):
    """
    Reusable status indicator with colored dot, label, and refresh button.

    Usage:
        indicator = StatusIndicator(
            check_fn=lambda: my_service.test_connection(),
            color_scheme=self.color_scheme,
            parent=self
        )
        layout.addWidget(indicator)

        # check_fn returns Tuple[bool, str]: (is_ok, status_message)
        # True → CONNECTED state, False → DISCONNECTED state
    """

    def __init__(
        self,
        check_fn: Callable[[], tuple[bool, str]] | None = None,
        color_scheme: ColorScheme | None = None,
        show_refresh: bool = True,
        debounce_ms: int = DEFAULT_DEBOUNCE_MS,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._check_fn = check_fn
        self._color_scheme = color_scheme or ColorScheme()
        self._debounce_ms = debounce_ms
        self._task_manager = BackgroundTaskManager()

        self._setup_ui(show_refresh)

    def _setup_ui(self, show_refresh: bool):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Colored dot
        self._dot = QLabel("●")
        self._dot.setFixedWidth(12)
        layout.addWidget(self._dot)

        # Status text
        self._label = QLabel("Unknown")
        self._label.setFont(QFont("Arial", 8))
        layout.addWidget(self._label)

        # Refresh button (optional)
        if show_refresh:
            self._refresh_btn = QPushButton("↻")
            self._refresh_btn.setFixedSize(20, 20)
            self._refresh_btn.setToolTip("Refresh status")
            self._refresh_btn.clicked.connect(self.refresh)
            layout.addWidget(self._refresh_btn)
        else:
            self._refresh_btn = None

        self.set_state(StatusState.UNKNOWN)

    def set_state(self, state: StatusState, message: str | None = None) -> None:
        """Update visual state."""
        color = state.color_role.color_hex(self._color_scheme)
        self._dot.setStyleSheet(f"color: {color};")
        self._label.setText(message or state.default_message or "")

        if self._refresh_btn:
            self._refresh_btn.setEnabled(state != StatusState.CHECKING)

    present_checking = partialmethod(set_state, StatusState.CHECKING)
    present_connected = partialmethod(set_state, StatusState.CONNECTED)
    present_disconnected = partialmethod(set_state, StatusState.DISCONNECTED)
    present_warning = partialmethod(set_state, StatusState.WARNING)

    def refresh(self, force: bool = False):
        """Trigger async status check."""
        if self._check_fn is None:
            return

        # Only set CHECKING if task actually starts (not debounced)
        task = self._task_manager.run(
            target=self._check_fn,
            on_success=self._on_check_complete,
            on_error=self._on_check_error,
            debounce_ms=0 if force else self._debounce_ms  # No debounce on force
        )
        if task is not None:
            self.set_state(StatusState.CHECKING)

    def _on_check_complete(self, result: tuple[bool, str]):
        """Handle check result."""
        is_ok, message = result
        state = StatusState.CONNECTED if is_ok else StatusState.DISCONNECTED
        self.set_state(state, message)

    def _on_check_error(self, error: Exception):
        """Handle check error."""
        self.set_state(StatusState.DISCONNECTED, f"Error: {str(error)}")

    def showEvent(self, event):  # noqa: N802 - Qt virtual method name
        """Auto-refresh on show (no debounce for initial check)."""
        super().showEvent(event)
        self.refresh(force=True)

    def closeEvent(self, event):  # noqa: N802 - Qt virtual method name
        """Cleanup on close."""
        self._task_manager.cleanup()
        super().closeEvent(event)
