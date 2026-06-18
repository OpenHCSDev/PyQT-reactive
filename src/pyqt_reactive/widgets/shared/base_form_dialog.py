"""
Base Form Dialog for PyQt6.

Generic base class for managed ObjectState-backed dialogs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QDialog, QLabel, QPushButton

from pyqt_reactive.services.window_manager import WindowManager
from pyqt_reactive.services.window_navigation import (
    NullWindowNavigationDriver,
    WindowNavigationDriver,
)
from pyqt_reactive.services.window_code_document import WindowCodeDocumentDriver
from pyqt_reactive.widgets.shared.dirty_window_presenter import (
    DirtyWindowPresentation,
    DirtyWindowPresenter,
    DirtyWindowStateTracker,
)
from pyqt_reactive.widgets.shared.scoped_border_mixin import ScopedBorderMixin

if TYPE_CHECKING:
    from objectstate import ObjectState

    from pyqt_reactive.forms.parameter_form_manager import ParameterFormManager


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ManagedStateRestorePolicy:
    """ObjectState restore behavior for managed window close/cancel."""

    propagate_descendants: bool = True

    def restore(self, state: "ObjectState") -> None:
        """Restore ObjectState according to this policy."""
        state.restore_saved(propagate_descendants=self.propagate_descendants)


@dataclass(frozen=True, slots=True)
class ManagedWindowActionCapabilities:
    """Agent-visible actions supported by a managed form window."""

    save_and_close: bool = False
    save_without_close: bool = False
    discard_and_close: bool = True


class BaseManagedWindow(QDialog, ScopedBorderMixin):
    """Base class for managed windows with WindowManager integration.

    Subclasses declare their ObjectState/form lifecycle through hooks instead
    of relying on structural attribute discovery.
    """

    changes_detected = pyqtSignal(bool)

    scope_id: str | None = None
    state: "ObjectState | None" = None
    state_restore_policy = ManagedStateRestorePolicy()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._flash_overlay_cleaned = False
        self._change_detection_connected = False
        self._dirty_window_presenter = DirtyWindowPresenter()
        self._dirty_window_state = DirtyWindowStateTracker(
            state_provider=lambda: self.state,
            change_emitter=self.changes_detected.emit,
        )
        self.changes_detected.connect(self.on_changes_detected)

    def setup_save_button(self, button: QPushButton, save_callback: Callable) -> None:
        """Connect a save button with Shift+Click save-without-close behavior."""

        def on_save_clicked() -> None:
            from PyQt6.QtWidgets import QApplication

            modifiers = QApplication.keyboardModifiers()
            is_shift = modifiers & Qt.KeyboardModifier.ShiftModifier
            save_callback(close_window=not is_shift)

        button.clicked.connect(on_save_clicked)

    def form_managers(self) -> tuple["ParameterFormManager", ...]:
        """Return root form managers participating in change detection."""
        return ()

    def window_navigation_driver(self) -> WindowNavigationDriver:
        """Return the WindowManager navigation driver for this window."""
        return NullWindowNavigationDriver()

    def window_code_document_driver(self) -> WindowCodeDocumentDriver | None:
        """Return the optional code-document driver for this window."""
        return None

    @property
    def dirty_state(self) -> DirtyWindowStateTracker:
        """Return shared dirty/signature tracking for this window."""
        return self._dirty_window_state

    def dirty_window_widgets(self) -> tuple[QLabel, QPushButton] | None:
        """Return widgets updated by dirty presentation, if this window has them."""
        return None

    def dirty_window_presentation(self) -> DirtyWindowPresentation | None:
        """Return current dirty-state presentation, if this window has one."""
        return None

    def managed_window_action_capabilities(
        self,
    ) -> ManagedWindowActionCapabilities:
        """Return agent-visible managed-window actions for this window."""
        return ManagedWindowActionCapabilities()

    def agent_save_managed_window(self, *, close_window: bool) -> None:
        """Save this managed window through its domain save workflow."""
        raise NotImplementedError(
            f"{type(self).__name__} does not expose managed-window save."
        )

    def agent_discard_and_close_managed_window(self) -> None:
        """Discard unsaved edits and close through the normal cancel path."""
        self.reject()

    def apply_dirty_window_presentation(self) -> None:
        """Apply this window's current dirty presentation to its widgets."""
        widgets = self.dirty_window_widgets()
        presentation = self.dirty_window_presentation()
        if widgets is None or presentation is None:
            return
        header_label, save_button = widgets
        self._dirty_window_presenter.apply(
            window=self,
            header_label=header_label,
            save_button=save_button,
            presentation=presentation,
        )

    def detect_changes(self) -> None:
        """Detect edits through the shared ObjectState dirty tracker."""
        self._dirty_window_state.detect_changes()

    def on_changes_detected(self, has_changes: bool) -> None:
        """React to managed dirty-state changes."""
        del has_changes
        self.apply_dirty_window_presentation()

    def show(self) -> None:
        """Override show to enforce singleton-per-scope behavior."""
        scope_key = self.scope_id
        if scope_key is None:
            super().show()
            return

        if WindowManager.is_open(scope_key):
            WindowManager.focus_and_navigate(scope_key)
            logger.debug("[SINGLETON] Focused existing window for %s", scope_key)
            return

        WindowManager.register(
            scope_key,
            self,
            navigation_driver=self.window_navigation_driver(),
            code_document_driver=self.window_code_document_driver(),
        )
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
        self._unregister_managed_window()

    def mark_saved_and_refresh_all(self) -> None:
        """Mark the managed state saved and notify other windows."""
        state = self.state
        if state:
            logger.debug("[BASE_FORM_DIALOG] Marking ObjectState as saved")
            state.mark_saved()

        from objectstate import ObjectStateRegistry

        ObjectStateRegistry.increment_token(notify=True)
        logger.debug("[BASE_FORM_DIALOG] Triggered global refresh after save")

    def finish_managed_save(self, *, close_window: bool) -> None:
        """Complete a successful managed-window save."""
        if close_window:
            self.accept()
        else:
            self.mark_saved_and_refresh_all()
        self.detect_changes()

    def reject(self):
        """Restore the managed ObjectState before rejecting the dialog."""
        state = self.state
        if state:
            logger.debug("[BASE_FORM_DIALOG] Restoring ObjectState to saved state")
            self.state_restore_policy.restore(state)

        super().reject()
        self._unregister_managed_window()

    def closeEvent(self, event):
        """Restore managed state and unregister the window on close."""
        state = self.state
        if state:
            logger.debug("[BASE_FORM_DIALOG] Restoring ObjectState on closeEvent")
            self.state_restore_policy.restore(state)

        self._unregister_managed_window()
        super().closeEvent(event)

    def _unregister_managed_window(self) -> None:
        """Remove this managed window from WindowManager singleton tracking."""
        scope_key = self.scope_id
        if scope_key:
            WindowManager.unregister(scope_key)

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
        value,
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
