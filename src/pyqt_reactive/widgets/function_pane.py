"""
Function Pane Widget for PyQt6

Individual function display with parameter editing capabilities.
Uses GroupBoxWithHelp as the main container for consistent formatting
and enableable support.
"""

import logging
from typing import Any, Dict, Callable, Optional, Tuple, List, Set

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QScrollArea, QSizePolicy, QLayout
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from python_introspect import SignatureAnalyzer, is_enableable, ENABLED_FIELD

# Import PyQt6 help components (using same pattern as Textual TUI)
from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.shared.clickable_help_components import GroupBoxWithHelp
from pyqt_reactive.forms import ParameterFormManager
from pyqt_reactive.animation import FlashMixin

logger = logging.getLogger(__name__)


class FunctionPaneWidget(GroupBoxWithHelp):
    """
    PyQt6 Function Pane Widget.
    
    Displays individual function with editable parameters and control buttons.
    Uses GroupBoxWithHelp as the main container for consistent formatting
    and enableable support.
    """
    
    # Signals
    parameter_changed = pyqtSignal(int, str, object)  # index, param_name, value
    function_changed = pyqtSignal(int)  # index
    add_function = pyqtSignal(int)  # index
    remove_function = pyqtSignal(int)  # index
    move_function = pyqtSignal(int, int)  # index, direction
    reset_parameters = pyqtSignal(int)  # index
    
    def __init__(self, func_item: Tuple[Callable, Dict], index: int, service_adapter, color_scheme: Optional[ColorScheme] = None,
                 step_instance=None, scope_id: Optional[str] = None, parent=None):
        """
        Initialize the function pane widget.

        Args:
            func_item: Tuple of (function, kwargs)
            index: Function index in the list
            service_adapter: PyQt service adapter for dialogs and operations
            color_scheme: Color scheme for UI components
            step_instance: Step instance for context hierarchy (Function → Step → Pipeline → Global)
            scope_id: Scope identifier for cross-window live context updates
            parent: Parent widget
        """
        # Extract function info before calling super().__init__
        func, kwargs = func_item
        self.func = func
        self.kwargs = kwargs
        
        # Determine title and help target
        if func:
            title = f"🔧 {func.__name__}"
            help_target = func  # type: ignore
        else:
            title = "No Function Selected"
            help_target = None  # type: ignore
        
        # Initialize GroupBoxWithHelp
        super().__init__(
            title=title,
            help_target=help_target,
            color_scheme=color_scheme,
            parent=parent
        )

        # Initialize color scheme
        self.color_scheme = color_scheme or ColorScheme()

        # Core dependencies
        self.service_adapter = service_adapter

        # CRITICAL: Store step instance for context hierarchy
        self.step_instance = step_instance

        # CRITICAL: Store scope_id for cross-window live context updates
        self.scope_id = scope_id

        # Business logic state
        self.index = index
        self.show_parameters = True
        
        # Parameter management
        if self.func:
            param_info = SignatureAnalyzer.analyze(self.func)
            # Store function signature defaults
            self.param_defaults = {name: info.default_value for name, info in param_info.items()}
        else:
            self.param_defaults = {}

        # Form manager will be created in create_parameter_form() when UI is built
        self.form_manager: Optional[ParameterFormManager] = None
        
        # Internal kwargs tracking
        self._internal_kwargs = self.kwargs.copy()
        
        # UI components
        self.parameter_widgets: Dict[str, QWidget] = {}
        self._enabled_checkbox: Optional[Any] = None

        # Scope color scheme
        self._scope_color_scheme: Optional[Any] = None

        # Track if enabled widget was moved to title (prevents race conditions)
        self._enabled_widget_moved: bool = False

        # Setup UI
        self.setup_ui()
        self.setup_connections()
        
        logger.debug(f"Function pane widget initialized for index {index}")
    
    def setup_ui(self):
        """Setup the user interface."""
        # Add module path above the title if function exists
        if self.func and self.func.__module__:
            self._add_module_path_above_title()
        
        # Add control buttons to title area
        self._add_control_buttons_to_title()

        # Parameter form (if function exists and parameters shown)
        if self.func and self.show_parameters:
            parameter_frame = self.create_parameter_form()
            self.content_layout.addWidget(parameter_frame)
            
            # For enableable functions: move enabled widget to title after form is built
            # CRITICAL: Must use callback because form manager builds widgets asynchronously
            if is_enableable(self.func) and self.form_manager is not None:
                # Check if form is already built (sync path) - move immediately
                if len(self.form_manager.widgets) > 0 and ENABLED_FIELD in self.form_manager.widgets:
                    # Form already built, move enabled widget now
                    self._move_enabled_widget_to_title()
                else:
                    # Form not built yet (async path) - register callback
                    callbacks: list = self.form_manager._on_build_complete_callbacks
                    callbacks.append(lambda: self._move_enabled_widget_to_title())

        # Set size policy to only take minimum vertical space needed
        size_policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setSizePolicy(size_policy)

    def _add_module_path_above_title(self):
        """Add module path label above the title area."""
        func_module = self.func.__module__
        if func_module:
            # Show the full module path
            module_label = QLabel(func_module)
            module_label.setFont(QFont("Arial", 8))
            module_label.setStyleSheet(f"color: {self.color_scheme.to_hex(self.color_scheme.text_disabled)}; padding: 2px 0;")
            
            # Find the main layout and insert module path at index 0 (before title)
            main_layout = self.layout()
            if main_layout and isinstance(main_layout, QVBoxLayout):
                # Insert at position 0, before the title widget
                main_layout.insertWidget(0, module_label)

    def _add_control_buttons_to_title(self):
        """Add control buttons (move, add, delete, reset) to the title area."""
        # Button configurations: (symbol, action, tooltip)
        # Using symbols only for cleaner UI, tooltips provide context
        button_configs = [
            ("↑", "move_up", None),  # Removed "Move function up" label
            ("↓", "move_down", None),  # Removed "Move function down" label
            ("Add", "add_func", None),  # Removed "Add new function" label
            ("Del", "remove_func", None),  # Removed "Delete this function" label
            ("Reset", "reset_all", None),  # Removed "Reset all parameters" label
        ]

        button_style = f"""
            QPushButton {{
                background-color: {self.color_scheme.to_hex(self.color_scheme.input_bg)};
                color: {self.color_scheme.to_hex(self.color_scheme.text_primary)};
                border: none;
                border-radius: 3px;
                padding: 4px 8px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {self.color_scheme.to_hex(self.color_scheme.button_hover_bg)};
            }}
            QPushButton:pressed {{
                background-color: {self.color_scheme.to_hex(self.color_scheme.button_pressed_bg)};
            }}
        """

        for name, action, tooltip in button_configs:
            button = QPushButton(name)
            button.setToolTip(tooltip)
            button.setStyleSheet(button_style)
            button.setMaximumWidth(40 if len(name) <= 2 else 50)
            button.setFixedHeight(22)

            # Connect button to action
            button.clicked.connect(lambda checked, a=action: self.handle_button_action(a))

            self.addTitleWidget(button)

    def _move_enabled_widget_to_title(self):
        """
        Move the enabled widget from the form to the title area.

        This follows the same pattern as _move_enabled_widget_to_title in widget_creation_config.py
        for enableable dataclasses in GroupBoxWithHelp containers.
        """
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QLabel
        from pyqt_reactive.widgets.no_scroll_spinbox import NoneAwareCheckBox

        # Prevent multiple moves (can be called from callback multiple times)
        if hasattr(self, '_enabled_widget_moved') and self._enabled_widget_moved:
            return

        if not self.form_manager:
            return

        if ENABLED_FIELD not in self.form_manager.widgets:
            logger.debug(f"No enabled field found in form_manager.widgets for {self.func.__name__ if self.func else 'unknown'}")
            return

        # Mark as moved first to prevent race conditions
        self._enabled_widget_moved = True
        
        enabled_widget = self.form_manager.widgets[ENABLED_FIELD]
        enabled_reset_button = self.form_manager.reset_buttons.get(ENABLED_FIELD)
        enabled_label = self.form_manager.labels.get(ENABLED_FIELD)
        
        # Find the row layout that contains the enabled widget
        enabled_widget_parent = enabled_widget.parent()
        if not enabled_widget_parent:
            return
        
        enabled_widget_layout = enabled_widget_parent.layout()
        if not enabled_widget_layout:
            return
        
        # Remove the label (which contains the help button) from the row layout
        if enabled_label:
            enabled_widget_layout.removeWidget(enabled_label)
            enabled_label.hide()
        
        # Remove the enabled widget from the row layout
        enabled_widget_layout.removeWidget(enabled_widget)
        
        # Remove the enabled reset button from the row layout if it exists
        if enabled_reset_button:
            enabled_widget_layout.removeWidget(enabled_reset_button)
        
        # Make title clickable to toggle enabled checkbox
        if hasattr(self, '_title_label') and isinstance(enabled_widget, NoneAwareCheckBox):
            self._title_label.mousePressEvent = lambda e: enabled_widget.toggle()
            self._title_label.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Compact checkbox for title
        if isinstance(enabled_widget, NoneAwareCheckBox):
            enabled_widget.setMaximumWidth(20)
        
        # Add the enabled widget and reset button to the title layout using clean API
        if hasattr(self, 'addEnableableWidgets'):
            self.addEnableableWidgets(enabled_widget, enabled_reset_button)
        else:
            # Fallback for backwards compatibility
            self.addTitleInlineWidget(enabled_widget)
            if enabled_reset_button:
                self.addTitleInlineWidget(enabled_reset_button)
        
        # Clean up the empty row layout if possible
        if enabled_widget_layout.count() == 0:
            row_parent = enabled_widget_layout.parent()
            if isinstance(row_parent, QWidget):
                row_parent.setParent(None)
        
        logger.debug(f"Moved enabled widget to title for function {self.func.__name__}")

    def set_scope_color_scheme(self, scheme) -> None:
        """Set scope color scheme for title color styling."""
        logger.info(f"🎨 FunctionPaneWidget.set_scope_color_scheme: scheme={scheme is not None}")
        self._scope_color_scheme = scheme
        
        # Call parent class method to handle border/background
        super().set_scope_color_scheme(scheme)
        
        # Update title label color
        if hasattr(self, '_title_label') and scheme:
            from pyqt_reactive.widgets.shared.scope_color_utils import tint_color_perceptual
            accent_color = tint_color_perceptual(scheme.base_color_rgb, 1)
            logger.info(f"🎨 FunctionPaneWidget: Setting title color to {accent_color.name()}")
            self._title_label.setStyleSheet(f"color: {accent_color.name()};")
    
    def create_parameter_form(self) -> QWidget:
        """
        Create the parameter form using extracted business logic.
        
        Returns:
            Widget containing parameter form
        """
        # Create a simple container widget for the form (no longer using QGroupBox)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Create the ParameterFormManager with help and reset functionality
        # Import the enhanced PyQt6 ParameterFormManager
        from pyqt_reactive.forms import ParameterFormManager as PyQtParameterFormManager, FormManagerConfig

        # Create form manager with initial_values to load saved kwargs
        # CRITICAL: Pass step_instance as context_obj for lazy resolution hierarchy
        # Function parameters → Step → Pipeline → Global
        # CRITICAL: Pass scope_id for cross-window live context updates (real-time placeholder sync)
        # IMPORTANT UI BEHAVIOR:
        # - FunctionListWidget already wraps all FunctionPaneWidgets in a QScrollArea.
        # - If we also enable a scroll area inside ParameterFormManager here, the
        #   inner scroll will expand to fill the available height, making the
        #   "Parameters" pane look like it stretches to consume all vertical
        #   space even when only a few rows are present.
        # - To keep each function pane only as tall as its content, we explicitly
        #   disable the inner scroll area and let the outer FunctionListWidget
        #   handle scrolling for long forms.

        # Optional imports - stub if not available
        try:
            from objectstate import ObjectState, ObjectStateRegistry
        except ImportError:
            ObjectState = None  # type: ignore
            ObjectStateRegistry = None  # type: ignore

        try:
            from pyqt_reactive.services.scope_token_service import ScopeTokenService
        except ImportError:
            ScopeTokenService = None  # type: ignore

        # Build function-specific scope: step_scope::func_N
        step_scope = self.scope_id or "no_scope"
        func_scope_id = ScopeTokenService.build_scope_id(step_scope, self.func)

        # Check if ObjectState already exists (e.g., from time travel restore)
        # If so, reuse it to preserve restored state; otherwise create new
        existing_state = ObjectStateRegistry.get_by_scope(func_scope_id)
        if existing_state:
            func_state = existing_state
            self._func_state = None  # Don't cleanup - we didn't create it
        else:
            # Get parent state (step state) from registry for context inheritance
            parent_state = ObjectStateRegistry.get_by_scope(step_scope)
            func_state = ObjectState(
                object_instance=self.func,
                scope_id=func_scope_id,
                parent_state=parent_state,
                initial_values=self.kwargs,
            )
            ObjectStateRegistry.register(func_state)
            self._func_state = func_state  # Store for cleanup

        self.form_manager = PyQtParameterFormManager(
            state=func_state,
            config=FormManagerConfig(
                parent=self,                      # Pass self as parent widget
                color_scheme=self.color_scheme,   # Pass color_scheme for consistent theming
                use_scroll_area=False,            # Let outer FunctionListWidget manage scrolling
            )
        )

        # Forward function parameter changes to parent step state for list item flash
        # Uses ObjectState.forward_to_parent_state('func') to notify parent its 'func' field changed
        # Note: Per-parameter flashing is handled automatically by the PFM
        if func_state._parent_state is not None:
            def forward_to_step(changed_paths):
                # Notify parent state that its 'func' field conceptually changed
                func_state.forward_to_parent_state('func')
            func_state.on_resolved_changed(forward_to_step)
            logger.info(f"[FUNCTION_PANE] Registered parent notification: {func_scope_id} → {step_scope}")

        # Connect parameter changes
        self.form_manager.parameter_changed.connect(
            lambda param_name, value: self.handle_parameter_change(param_name, value)
        )

        layout.addWidget(self.form_manager)

        return container

    def cleanup_object_state(self) -> None:
        """Unregister ObjectState on widget destruction."""
        try:
            from objectstate import ObjectStateRegistry
            if hasattr(self, '_func_state') and self._func_state:
                ObjectStateRegistry.unregister(self._func_state)
                self._func_state = None
        except ImportError:
            pass  # ObjectStateRegistry not available

    def create_parameter_widget(self, param_name: str, param_type: type, current_value: Any) -> Optional[QWidget]:
        """
        Create parameter widget based on type.

        Args:
            param_name: Parameter name
            param_type: Parameter type
            current_value: Current parameter value

        Returns:
            Widget for parameter editing or None
        """
        from PyQt6.QtWidgets import QLineEdit
        from pyqt_reactive.widgets import (
            NoScrollSpinBox, NoScrollDoubleSpinBox
        )

        # Boolean parameters
        if param_type == bool:
            from pyqt_reactive.widgets import NoneAwareCheckBox
            widget = NoneAwareCheckBox()
            widget.set_value(current_value)  # Use set_value to handle None properly
            widget.toggled.connect(lambda checked: self.handle_parameter_change(param_name, checked))
            return widget

        # Integer parameters
        elif param_type == int:
            widget = NoScrollSpinBox()
            widget.setRange(-999999, 999999)
            widget.setValue(int(current_value) if current_value is not None else 0)
            widget.valueChanged.connect(lambda value: self.handle_parameter_change(param_name, value))
            return widget

        # Float parameters
        elif param_type == float:
            from pyqt_reactive.forms.widget_strategies import WidgetConfig
            widget = NoScrollDoubleSpinBox()
            widget.setRange(-999999.0, 999999.0)
            widget.setDecimals(WidgetConfig.FLOAT_PRECISION)
            widget.setValue(float(current_value) if current_value is not None else 0.0)
            widget.valueChanged.connect(lambda value: self.handle_parameter_change(param_name, value))
            return widget

        # Enum parameters
        elif any(base.__name__ == 'Enum' for base in param_type.__bases__):
            from pyqt_reactive.forms.widget_strategies import create_enum_widget_unified

            # Use the single source of truth for enum widget creation
            widget = create_enum_widget_unified(param_type, current_value)

            widget.currentIndexChanged.connect(
                lambda index: self.handle_parameter_change(param_name, widget.itemData(index))
            )
            return widget

        # String and other parameters
        else:
            widget = QLineEdit()
            widget.setText(str(current_value) if current_value is not None else "")
            widget.textChanged.connect(lambda text: self.handle_parameter_change(param_name, text))
            return widget
    
    def setup_connections(self):
        """Setup signal/slot connections."""
        pass  # Connections are set up in widget creation
    
    def handle_button_action(self, action: str):
        """
        Handle button actions (extracted from Textual version).
        
        Args:
            action: Action identifier
        """
        if action == "move_up":
            self.move_function.emit(self.index, -1)
        elif action == "move_down":
            self.move_function.emit(self.index, 1)
        elif action == "add_func":
            self.add_function.emit(self.index + 1)
        elif action == "remove_func":
            self.remove_function.emit(self.index)
        elif action == "reset_all":
            self.reset_all_parameters()
    
    def handle_parameter_change(self, param_name: str, value: Any):
        """
        Handle parameter value changes (extracted from Textual version).

        Args:
            param_name: Full path like "func_0.sigma" or just "func_0.param_name"
            value: New parameter value
        """
        # Extract leaf field name from full path
        # "func_0.sigma" -> "sigma"
        leaf_field = param_name.split('.')[-1]

        # Update internal kwargs without triggering reactive update
        self._internal_kwargs[leaf_field] = value

        # The form manager already has the updated value (it emitted this signal)
        # No need to call update_parameter() again - that would be redundant

        # Emit parameter changed signal to notify parent (function list editor)
        self.parameter_changed.emit(self.index, leaf_field, value)

        logger.debug(f"Parameter changed: {param_name} = {value}")
    
    def reset_all_parameters(self):
        """Reset all parameters to default values using PyQt6 form manager."""
        if not self.form_manager:
            return

        # Reset all parameters - form manager will use signature defaults from param_defaults
        for param_name in list(self.form_manager.parameters.keys()):
            self.form_manager.reset_parameter(param_name)

        # Update internal kwargs to match the reset values
        # Use form_manager.state which always has the correct ObjectState reference
        if self.form_manager.state:
            self._internal_kwargs = self.form_manager.state.get_current_values()

        # Emit parameter changed signals for each reset parameter
        for param_name, default_value in self.param_defaults.items():
            self.parameter_changed.emit(self.index, param_name, default_value)

        self.reset_parameters.emit(self.index)
    
    def update_widget_value(self, widget: QWidget, value: Any):
        """
        Update widget value without triggering signals.
        
        Args:
            widget: Widget to update
            value: New value
        """
        from PyQt6.QtWidgets import QLineEdit, QCheckBox, QSpinBox, QDoubleSpinBox, QComboBox
        # Import the no-scroll classes from single source of truth
        from pyqt_reactive.widgets import (
            NoScrollSpinBox, NoScrollDoubleSpinBox, NoScrollComboBox
        )
        
        # Temporarily block signals to avoid recursion
        widget.blockSignals(True)
        
        try:
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, (QSpinBox, NoScrollSpinBox)):
                widget.setValue(int(value) if value is not None else 0)
            elif isinstance(widget, (QDoubleSpinBox, NoScrollDoubleSpinBox)):
                widget.setValue(float(value) if value is not None else 0.0)
            elif isinstance(widget, (QComboBox, NoScrollComboBox)):
                for i in range(widget.count()):
                    if widget.itemData(i) == value:
                        widget.setCurrentIndex(i)
                        break
            elif isinstance(widget, QLineEdit):
                widget.setText(str(value) if value is not None else "")
        finally:
            widget.blockSignals(False)
    
    def get_current_kwargs(self) -> Dict[str, Any]:
        """
        Get current kwargs values (extracted from Textual version).
        
        Returns:
            Current parameter values
        """
        return self._internal_kwargs.copy()
    
    def sync_kwargs(self):
        """Sync internal kwargs to main kwargs (extracted from Textual version)."""
        self.kwargs = self._internal_kwargs.copy()
    
    def update_function(self, func_item: Tuple[Callable, Dict]):
        """
        Update the function and parameters.
        
        Args:
            func_item: New function item tuple
        """
        self.func, self.kwargs = func_item
        self._internal_kwargs = self.kwargs.copy()
        
        # Update parameter defaults
        if self.func:
            param_info = SignatureAnalyzer.analyze(self.func)
            # Store function signature defaults
            self.param_defaults = {name: info.default_value for name, info in param_info.items()}
        else:
            self.param_defaults = {}

        # Form manager will be recreated in create_parameter_form() when UI is rebuilt
        self.form_manager = None

        # Rebuild UI (this will create the form manager in create_parameter_form())
        self.setup_ui()
        
        logger.debug(f"Updated function for index {self.index}")


class FunctionListWidget(QWidget):
    """
    PyQt6 Function List Widget.
    
    Container for multiple FunctionPaneWidgets with list management.
    """
    
    # Signals
    functions_changed = pyqtSignal(list)  # List of function items
    
    def __init__(self, service_adapter, color_scheme: Optional[ColorScheme] = None, parent=None):
        """
        Initialize the function list widget.
        
        Args:
            service_adapter: PyQt service adapter
            parent: Parent widget
        """
        super().__init__(parent)

        # Initialize color scheme
        self.color_scheme = color_scheme or ColorScheme()
        
        self.service_adapter = service_adapter
        self.functions: List[Tuple[Callable, Dict]] = []
        self.function_panes: List[FunctionPaneWidget] = []
        
        # Setup UI
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the user interface."""
        layout = QVBoxLayout(self)
        
        # Scroll area for function panes
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # Container widget for function panes
        self.container_widget = QWidget()
        self.container_layout = QVBoxLayout(self.container_widget)
        self.container_layout.setSpacing(5)
        
        scroll_area.setWidget(self.container_widget)
        layout.addWidget(scroll_area)
        
        # Add function button
        add_button = QPushButton("Add Function")
        add_button.clicked.connect(lambda: self.add_function_at_index(len(self.functions)))
        layout.addWidget(add_button)
    
    def update_function_list(self):
        """Update the function list display."""
        # Clear existing panes - CRITICAL: Manually unregister form managers BEFORE deleteLater()
        # This prevents RuntimeError when new widgets try to connect to deleted managers
        for pane in self.function_panes:
            # Unregister ObjectState
            if hasattr(pane, 'cleanup_object_state'):
                pane.cleanup_object_state()
            # Explicitly unregister the form manager before scheduling deletion
            if hasattr(pane, 'form_manager') and pane.form_manager is not None:
                try:
                    pane.form_manager.unregister_from_cross_window_updates()
                except RuntimeError:
                    pass  # Already deleted
            pane.deleteLater()  # Schedule for deletion - triggers destroyed signal
        self.function_panes.clear()
        
        # Create new panes
        for i, func_item in enumerate(self.functions):
            pane = FunctionPaneWidget(func_item, i, self.service_adapter, color_scheme=self.color_scheme)
            
            # Connect signals
            pane.parameter_changed.connect(self.on_parameter_changed)
            pane.add_function.connect(self.add_function_at_index)
            pane.remove_function.connect(self.remove_function_at_index)
            pane.move_function.connect(self.move_function)
            
            self.function_panes.append(pane)
            self.container_layout.addWidget(pane)
        
        self.container_layout.addStretch()
    
    def add_function_at_index(self, index: int):
        """Add function at specific index."""
        # Placeholder function
        new_func_item = (lambda x: x, {})
        self.functions.insert(index, new_func_item)
        self.update_function_list()
        self.functions_changed.emit(self.functions)
    
    def remove_function_at_index(self, index: int):
        """Remove function at specific index."""
        if 0 <= index < len(self.functions):
            self.functions.pop(index)
            self.update_function_list()
            self.functions_changed.emit(self.functions)
    
    def move_function(self, index: int, direction: int):
        """Move function up or down."""
        new_index = index + direction
        if 0 <= new_index < len(self.functions):
            self.functions[index], self.functions[new_index] = self.functions[new_index], self.functions[index]
            self.update_function_list()
            self.functions_changed.emit(self.functions)
    
    def on_parameter_changed(self, index: int, param_name: str, value: Any):
        """Handle parameter changes."""
        if 0 <= index < len(self.functions):
            func, kwargs = self.functions[index]
            new_kwargs = kwargs.copy()
            new_kwargs[param_name] = value
            self.functions[index] = (func, new_kwargs)
            self.functions_changed.emit(self.functions)
