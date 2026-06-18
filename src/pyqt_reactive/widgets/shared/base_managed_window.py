"""
Base Form Dialog for PyQt6

Generic base class for managed dialogs with WindowManager integration.
"""

import logging
from typing import Optional

from PyQt6.QtWidgets import QDialog
from pyqt_reactive.services.window_manager import WindowManager
from pyqt_reactive.animation import WindowFlashOverlay
from pyqt_reactive.services.window_navigation import (
    NullWindowNavigationDriver,
    WindowNavigationDriver,
)
from pyqt_reactive.services.window_code_document import WindowCodeDocumentDriver

logger = logging.getLogger(__name__)


class BaseManagedWindow(QDialog):
    """Base class for managed windows with WindowManager integration.

    Provides singleton-per-scope behavior via WindowManager.
    Subclasses implement create_widget() to specify content.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._flash_overlay_cleaned = False

    def show(self) -> None:
        """Override show to enforce singleton-per-scope behavior."""
        scope_key = self._get_window_scope_key()
        if scope_key is None:
            super().show()
            return

        if WindowManager.is_open(scope_key):
            WindowManager.focus_and_navigate(scope_key)
            logger.debug(f"[SINGLETON] Focused existing window for {scope_key}")
            return

        WindowManager.register(
            scope_key,
            self,
            navigation_driver=self.window_navigation_driver(),
            code_document_driver=self.window_code_document_driver(),
        )
        super().show()
        logger.debug(f"[SINGLETON] Registered and showed new window for {scope_key}")

    def closeEvent(self, event):
        """Handle close event with WindowManager cleanup."""
        scope_key = self._get_window_scope_key()
        if scope_key:
            WindowManager.unregister(scope_key)
        super().closeEvent(event)

    def _get_window_scope_key(self) -> Optional[str]:
        """Get unique key for WindowManager. Subclasses override."""
        return None

    def window_navigation_driver(self) -> WindowNavigationDriver:
        """Return the WindowManager navigation driver for this window."""
        return NullWindowNavigationDriver()

    def window_code_document_driver(self) -> WindowCodeDocumentDriver | None:
        """Return the optional code-document driver for this window."""
        return None
