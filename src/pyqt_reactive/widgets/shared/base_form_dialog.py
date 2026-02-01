"""
Base Form Dialog for PyQt6

Generic base class for managed dialogs with WindowManager integration.
"""

import logging
from typing import Optional, Callable

from PyQt6.QtWidgets import QDialog, QPushButton, QVBoxLayout, QHBoxLayout, QLabel, QWidget
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from pyqt_reactive.services.window_manager import WindowManager
from pyqt_reactive.animation import WindowFlashOverlay
from pyqt_reactive.widgets.shared.scoped_border_mixin import ScopedBorderMixin

logger = logging.getLogger(__name__)


class BaseManagedWindow(QDialog, ScopedBorderMixin):
    """Base class for managed windows with WindowManager integration.

    Provides singleton-per-scope behavior via WindowManager.
    Subclasses implement create_widget() to specify content.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._flash_overlay_cleaned = False
        self._change_detection_connected = False

    def _setup_save_button(self, button: QPushButton, save_callback: Callable) -> None:
        """
        Setup save button with Shift+Click detection for 'Save without close' functionality.

        Args:
            button: The save button widget
            save_callback: The save method to call (must accept close_window keyword argument)

        Pattern:
            - Normal click: save_callback(close_window=True) - saves and closes window
            - Shift+Click: save_callback(close_window=False) - saves but keeps window open

        This mirrors the pattern from SimpleCodeEditor and is used by:
        - DualEditorWindow.save_edit(*, close_window=True)
        - ConfigWindow.save_config(*, close_window=True)
        """
        def on_save_clicked():
            """Handle save button click with Shift+Click detection."""
            from PyQt6.QtWidgets import QApplication
            modifiers = QApplication.keyboardModifiers()
            is_shift = modifiers & Qt.KeyboardModifier.ShiftModifier
            save_callback(close_window=not is_shift)

        button.clicked.connect(on_save_clicked)

    def _create_compact_header(self, parent_layout: QVBoxLayout, title_text: str,
                               title_color: Optional[str] = None) -> tuple[QLabel, QHBoxLayout]:
        """
        Create a compact two-row header for narrow windows.

        Row 1: Title only (full width, centered or left-aligned)
        Row 2: Button row (for caller to add buttons to)

        This layout allows windows to be narrower by separating the title
        from action buttons, preventing horizontal crowding.

        Args:
            parent_layout: The parent QVBoxLayout to add headers to
            title_text: The header title text
            title_color: Optional hex color for title (uses text_accent if None)

        Returns:
            Tuple of (title_label, button_layout) - add your buttons to button_layout

        Usage:
            title_label, button_layout = self._create_compact_header(layout, "My Title")
            button_layout.addWidget(save_button)
            button_layout.addWidget(cancel_button)
        """
        from pyqt_reactive.theming import ColorScheme

        # Row 1: Title only
        title_widget = QWidget()
        title_layout = QHBoxLayout(title_widget)
        title_layout.setContentsMargins(4, 4, 4, 4)
        title_layout.setSpacing(0)

        title_label = QLabel(title_text)
        title_label.setFont(QFont("Arial", 14, QFont.Weight.Bold))

        # Use provided color or get from color scheme
        if title_color is None:
            color_scheme = ColorScheme()
            title_color = color_scheme.to_hex(color_scheme.text_accent)
        title_label.setStyleSheet(f"color: {title_color};")

        title_layout.addWidget(title_label)
        title_layout.addStretch()  # Push title to left

        parent_layout.addWidget(title_widget)

        # Row 2: Button row
        button_widget = QWidget()
        button_layout = QHBoxLayout(button_widget)
        button_layout.setContentsMargins(4, 2, 4, 2)
        button_layout.setSpacing(8)

        button_layout.addStretch()  # Push buttons to right

        parent_layout.addWidget(button_widget)

        return title_label, button_layout

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

        WindowManager.register(scope_key, self)
        super().show()
        QTimer.singleShot(0, lambda: WindowManager.position_window_near_cursor(self))
        logger.debug(f"[SINGLETON] Registered and showed new window for {scope_key}")

    def accept(self):
        """Handle dialog acceptance (Save button without Shift).

        Marks ObjectState as saved before closing.
        Subclasses should call super().accept() to ensure state is marked as saved.
        """
        # Mark ObjectState as saved (updates saved baseline)
        if hasattr(self, 'state') and self.state:
            logger.debug(f"[BASE_FORM_DIALOG] Marking ObjectState as saved on accept")
            self.state.mark_saved()

        # Call QDialog.accept() to close the window
        super().accept()

    def _mark_saved_and_refresh_all(self):
        """Mark ObjectState as saved and refresh all windows.

        Called when saving without closing (Shift+Click on Save button).
        Marks the current state as the new saved baseline and triggers
        cross-window refresh so other windows see the new saved values.
        """
        # Mark ObjectState as saved (updates saved baseline)
        if hasattr(self, 'state') and self.state:
            logger.debug(f"[BASE_FORM_DIALOG] Marking ObjectState as saved")
            self.state.mark_saved()

        # Trigger global refresh so other windows see the new saved values
        from objectstate import ObjectStateRegistry
        ObjectStateRegistry.increment_token(notify=True)
        logger.debug(f"[BASE_FORM_DIALOG] Triggered global refresh after save")

    def reject(self):
        """Handle dialog rejection (Cancel button or Escape key).

        Restores ObjectState to last saved state before closing.
        Subclasses should call super().reject() to ensure state restoration.
        """
        # Restore ObjectState to last saved state (undo unsaved changes)
        if hasattr(self, 'state') and self.state:
            logger.debug(f"[BASE_FORM_DIALOG] Restoring ObjectState to last saved state")
            self.state.restore_saved()

        # Call QDialog.reject() to close the window
        super().reject()

    def closeEvent(self, event):
        """Handle close event with WindowManager cleanup.

        Note: closeEvent is called when window is closed via X button,
        but NOT when closed via accept() or reject() buttons.
        """
        # Restore ObjectState when closing via X button (same as reject)
        if hasattr(self, 'state') and self.state:
            logger.debug(f"[BASE_FORM_DIALOG] Restoring ObjectState on closeEvent")
            self.state.restore_saved()

        scope_key = self._get_window_scope_key()
        if scope_key:
            WindowManager.unregister(scope_key)
        super().closeEvent(event)

    def _get_window_scope_key(self) -> Optional[str]:
        """Get unique key for WindowManager.

        Returns self.scope_id if it exists, otherwise None.
        This enables automatic WindowManager registration for all windows
        that have a scope_id attribute (ConfigWindow, DualEditorWindow, etc.).
        """
        return getattr(self, 'scope_id', None)

    def _connect_change_detection(self):
        """Connect to form manager's parameter_changed signal for automatic change detection.

        This method should be called after the window is fully initialized (after setup_ui
        and setup_connections). It automatically discovers form managers in the widget tree
        and connects to their parameter_changed signals.

        When a parameter changes, it calls self.detect_changes() if the method exists.
        This allows subclasses to implement custom change detection logic without
        manually connecting to parameter_changed signals.

        Pattern:
            - Subclass implements detect_changes() method
            - Subclass calls self._connect_change_detection() at end of __init__
            - BaseManagedWindow automatically calls detect_changes() when parameters change
        """
        if self._change_detection_connected:
            return

        # Find all ParameterFormManager instances in the widget tree
        form_managers = self._discover_form_managers()

        if not form_managers:
            logger.debug(f"[CHANGE_DETECTION] No form managers found in {self.__class__.__name__}")
            return

        # Connect to parameter_changed signal for each form manager
        for form_manager in form_managers:
            form_manager.parameter_changed.connect(self._on_parameter_changed_for_change_detection)
            logger.debug(f"[CHANGE_DETECTION] Connected to {form_manager.field_id} parameter_changed")

        self._change_detection_connected = True
        logger.debug(f"[CHANGE_DETECTION] Connected {len(form_managers)} form managers in {self.__class__.__name__}")

    def _discover_form_managers(self):
        """Discover all ParameterFormManager instances in the widget tree.

        Returns:
            List of ParameterFormManager instances found in the widget tree (including nested managers)
        """
        from pyqt_reactive.forms.parameter_form_manager import ParameterFormManager

        form_managers = []

        # Check common locations where form managers might be
        # 1. Direct attribute: self.form_manager
        if hasattr(self, 'form_manager'):
            form_manager = getattr(self, 'form_manager')
            if isinstance(form_manager, ParameterFormManager):
                form_managers.append(form_manager)
                # Recursively add nested managers
                form_managers.extend(self._get_nested_managers_recursively(form_manager))

        # 2. Nested in editor: self.step_editor.form_manager (DualEditorWindow pattern)
        if hasattr(self, 'step_editor') and hasattr(self.step_editor, 'form_manager'):
            form_manager = self.step_editor.form_manager
            if isinstance(form_manager, ParameterFormManager):
                form_managers.append(form_manager)
                # Recursively add nested managers
                form_managers.extend(self._get_nested_managers_recursively(form_manager))

        # 3. Nested in config_editor: self.config_editor.form_manager
        if hasattr(self, 'config_editor') and hasattr(self.config_editor, 'form_manager'):
            form_manager = self.config_editor.form_manager
            if isinstance(form_manager, ParameterFormManager):
                form_managers.append(form_manager)
                # Recursively add nested managers
                form_managers.extend(self._get_nested_managers_recursively(form_manager))

        return form_managers

    def _get_nested_managers_recursively(self, form_manager):
        """Recursively get all nested form managers from a form manager.

        Args:
            form_manager: The ParameterFormManager to get nested managers from

        Returns:
            List of all nested ParameterFormManager instances (recursively)
        """
        nested = []
        if hasattr(form_manager, 'nested_managers'):
            for nested_manager in form_manager.nested_managers.values():
                nested.append(nested_manager)
                # Recursively get nested managers from this nested manager
                nested.extend(self._get_nested_managers_recursively(nested_manager))
        return nested

    def _on_parameter_changed_for_change_detection(self, param_name: str, value):
        """Handle parameter changes for automatic change detection.

        Called when any parameter changes in any connected form manager.
        Calls self.detect_changes() if the method exists.

        Args:
            param_name: Full dotted path of the parameter that changed
            value: New value of the parameter
        """
        logger.debug(f"[CHANGE_DETECTION] _on_parameter_changed_for_change_detection called: param_name={param_name}")

        # Call detect_changes() if the subclass has implemented it
        if hasattr(self, 'detect_changes') and callable(getattr(self, 'detect_changes')):
            logger.debug(f"[CHANGE_DETECTION] Calling detect_changes() for {param_name}")
            self.detect_changes()  # type: ignore
        else:
            logger.debug(f"[CHANGE_DETECTION] No detect_changes() method found in {self.__class__.__name__}")


BaseFormDialog = BaseManagedWindow
"""Alias for backwards compatibility with OpenHCS code."""
