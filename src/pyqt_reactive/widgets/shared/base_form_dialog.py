"""
Base Form Dialog for PyQt6.

Generic base class for managed ObjectState-backed dialogs.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QDialog, QPushButton

from pyqt_reactive.services.window_manager import WindowManager
from pyqt_reactive.services.window_navigation import AvoidWidgetsWindow
from pyqt_reactive.widgets.shared.scoped_border_mixin import ScopedBorderMixin

if TYPE_CHECKING:
    from pyqt_reactive.forms.parameter_form_manager import ParameterFormManager


logger = logging.getLogger(__name__)


class BaseManagedWindow(QDialog, ScopedBorderMixin):
    """Base class for managed windows with WindowManager integration.

    Subclasses declare their ObjectState/form lifecycle through hooks instead
    of relying on structural attribute discovery.
    """

    state: Any | None = None
    restore_descendants_on_close: bool = True

    def __init__(self, parent=None):
        super().__init__(parent)
        self._avoid_widgets: list[Any] = []
        self._flash_overlay_cleaned = False
        self._change_detection_connected = False

    def setup_save_button(self, button: QPushButton, save_callback: Callable) -> None:
        """Connect a save button with Shift+Click save-without-close behavior."""

        def on_save_clicked() -> None:
            from PyQt6.QtWidgets import QApplication

            modifiers = QApplication.keyboardModifiers()
            is_shift = modifiers & Qt.KeyboardModifier.ShiftModifier
            save_callback(close_window=not is_shift)

        button.clicked.connect(on_save_clicked)

    def managed_scope_id(self) -> Optional[str]:
        """Return the WindowManager scope for this window."""
        return self.scope_id

    def form_managers(self) -> tuple["ParameterFormManager", ...]:
        """Return root form managers participating in change detection."""
        return ()

    def detect_changes(self) -> None:
        """Hook called after a managed form parameter changes."""
        return None

    def show(self) -> None:
        """Override show to enforce singleton-per-scope behavior."""
        scope_key = self.managed_scope_id()
        if scope_key is None:
            super().show()
            return

        if WindowManager.is_open(scope_key):
            WindowManager.focus_and_navigate(scope_key)
            logger.debug("[SINGLETON] Focused existing window for %s", scope_key)
            return

        WindowManager.register(scope_key, self)
        super().show()
        QTimer.singleShot(0, lambda: WindowManager.position_window_near_cursor(self))
        logger.debug("[SINGLETON] Registered and showed new window for %s", scope_key)

    def accept(self):
        """Mark the managed ObjectState saved before accepting the dialog."""
        state = self.state
        if state:
            logger.debug("[BASE_FORM_DIALOG] Marking ObjectState as saved on accept")
            state.mark_saved()

        super().accept()

    def mark_saved_and_refresh_all(self) -> None:
        """Mark the managed state saved and notify other windows."""
        state = self.state
        if state:
            logger.debug("[BASE_FORM_DIALOG] Marking ObjectState as saved")
            state.mark_saved()

        from objectstate import ObjectStateRegistry

        ObjectStateRegistry.increment_token(notify=True)
        logger.debug("[BASE_FORM_DIALOG] Triggered global refresh after save")

    def reject(self):
        """Restore the managed ObjectState before rejecting the dialog."""
        state = self.state
        if state:
            logger.debug("[BASE_FORM_DIALOG] Restoring ObjectState to saved state")
            state.restore_saved(
                propagate_descendants=self.restore_descendants_on_close
            )

        super().reject()

    def closeEvent(self, event):
        """Restore managed state and unregister the window on close."""
        state = self.state
        if state:
            logger.debug("[BASE_FORM_DIALOG] Restoring ObjectState on closeEvent")
            state.restore_saved(
                propagate_descendants=self.restore_descendants_on_close
            )

        scope_key = self.managed_scope_id()
        if scope_key:
            WindowManager.unregister(scope_key)
        super().closeEvent(event)

    def connect_change_detection(self) -> None:
        """Connect managed form managers to automatic change detection."""
        if self._change_detection_connected:
            return

        form_managers: list[ParameterFormManager] = []
        for form_manager in self.form_managers():
            form_managers.append(form_manager)
            form_managers.extend(self._nested_form_managers(form_manager))

        if not form_managers:
            logger.debug(
                "[CHANGE_DETECTION] No form managers found in %s",
                self.__class__.__name__,
            )
            return

        for form_manager in form_managers:
            form_manager.parameter_changed.connect(
                self._on_parameter_changed_for_change_detection
            )
            logger.debug(
                "[CHANGE_DETECTION] Connected to %s parameter_changed",
                form_manager.field_id,
            )

        self._change_detection_connected = True
        logger.debug(
            "[CHANGE_DETECTION] Connected %d form managers in %s",
            len(form_managers),
            self.__class__.__name__,
        )

    def _nested_form_managers(
        self,
        form_manager: "ParameterFormManager",
    ) -> list["ParameterFormManager"]:
        """Return all nested form managers rooted at one explicit form manager."""
        nested: list[ParameterFormManager] = []
        for nested_manager in form_manager.nested_managers.values():
            nested.append(nested_manager)
            nested.extend(self._nested_form_managers(nested_manager))
        return nested

    def _on_parameter_changed_for_change_detection(
        self,
        param_name: str,
        value: object,
    ) -> None:
        """Handle parameter changes for automatic change detection."""
        del value
        logger.debug(
            "[CHANGE_DETECTION] Calling detect_changes() for %s",
            param_name,
        )
        self.detect_changes()


BaseFormDialog = BaseManagedWindow
"""Alias for backwards compatibility with OpenHCS code."""


AvoidWidgetsWindow.register(BaseManagedWindow)
