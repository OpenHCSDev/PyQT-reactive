"""PyQt6 clickable help components - clean architecture without circular imports."""

import logging
from typing import Union, Callable, Optional
from PyQt6.QtWidgets import QLabel, QPushButton, QWidget, QHBoxLayout, QGroupBox, QVBoxLayout, QSizePolicy
from PyQt6.QtCore import Qt, pyqtSignal, pyqtProperty, QRect, QRectF, QSize
from PyQt6.QtGui import QFont, QCursor, QColor, QPainter, QPen

from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.animation import FlashMixin

logger = logging.getLogger(__name__)


class FlashableGroupBox(QGroupBox, FlashMixin):
    """QGroupBox that supports flash animation via overlay.

    GAME ENGINE ARCHITECTURE: Flash effects are rendered by a single
    WindowFlashOverlay per window, NOT by individual groupbox paintEvents.
    This scales O(1) per window regardless of how many items are animating.

    Inherits from FlashMixin to provide flash registration and queueing methods.
    """

    def __init__(self, title: str = "", parent: Optional[QWidget] = None,
                 flash_key: str = "", flash_manager=None):
        super().__init__(title, parent)
        self._flash_key = flash_key  # Key for overlay to look up geometry
        self._flash_manager = flash_manager  # Kept for backwards compat
        # Initialize FlashMixin state
        self._init_visual_update_mixin()

    # NOTE: paintEvent flash rendering REMOVED - now handled by WindowFlashOverlay
    # This eliminates O(n) paintEvent calls per frame


class ClickableHelpLabel(QLabel):
    """PyQt6 clickable label that shows help information - reuses Textual TUI help logic."""
    
    help_requested = pyqtSignal()
    
    def __init__(self, text: str, help_target: Union[Callable, type] = None,
                 param_name: str = None, param_description: str = None,
                 param_type: type = None, color_scheme: Optional[ColorScheme] = None, parent=None):
        """Initialize clickable help label.

        Args:
            text: Display text for the label
            help_target: Function or class to show help for (for function help)
            param_name: Parameter name (for parameter help)
            param_description: Parameter description (for parameter help)
            param_type: Parameter type (for parameter help)
            color_scheme: Color scheme for styling (optional, uses default if None)
        """
        # Add help indicator to text
        display_text = f"{text} (?)"
        super().__init__(display_text, parent)

        # Initialize color scheme
        self.color_scheme = color_scheme or ColorScheme()

        self.help_target = help_target
        self.param_name = param_name
        self.param_description = param_description
        self.param_type = param_type

        # Style as clickable
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(f"""
            QLabel {{
                color: {self.color_scheme.to_hex(self.color_scheme.selection_bg)};
                text-decoration: underline;
            }}
            QLabel:hover {{
                color: {self.color_scheme.to_hex(self.color_scheme.selection_bg)};
            }}
        """)
        
    def mousePressEvent(self, event):
        """Handle mouse press to show help - reuses Textual TUI help manager pattern."""
        if event.button() == Qt.MouseButton.LeftButton:
            try:
                # Import inside method to avoid circular imports (same pattern as Textual TUI)
                from pyqt_reactive.windows.help_window_manager import HelpWindowManager

                if self.help_target:
                    # Show function/class help using unified manager
                    HelpWindowManager.show_docstring_help(self.help_target, parent=self)
                elif self.param_name:
                    # Show parameter help using the description passed from parameter analysis
                    HelpWindowManager.show_parameter_help(
                        self.param_name, self.param_description or "No description available", self.param_type, parent=self
                    )

                self.help_requested.emit()

            except Exception as e:
                logger.error(f"Failed to show help: {e}")
                raise

        super().mousePressEvent(event)




class ClickableFunctionTitle(ClickableHelpLabel):
    """PyQt6 clickable function title that shows function documentation - mirrors Textual TUI."""

    def __init__(self, func: Callable, index: int = None, color_scheme: Optional[ColorScheme] = None, parent=None):
        func_name = getattr(func, '__name__', 'Unknown Function')
        module_name = getattr(func, '__module__', '').split('.')[-1] if func else ''

        # Build title text
        title = f"{index + 1}: {func_name}" if index is not None else func_name
        if module_name:
            title += f" ({module_name})"

        super().__init__(
            text=title,
            help_target=func,
            color_scheme=color_scheme,
            parent=parent
        )

        # Make title bold
        font = QFont()
        font.setBold(True)
        self.setFont(font)


class ClickableParameterLabel(ClickableHelpLabel):
    """PyQt6 clickable parameter label that shows parameter documentation - mirrors Textual TUI."""

    def __init__(self, param_name: str, param_description: str = None,
                 param_type: type = None, color_scheme: Optional[ColorScheme] = None, parent=None):
        # Format parameter name nicely
        display_name = param_name.replace('_', ' ').title()

        super().__init__(
            text=display_name,
            param_name=param_name,
            param_description=param_description or "No description available",
            param_type=param_type,
            color_scheme=color_scheme,
            parent=parent
        )


class HelpIndicator(QLabel):
    """PyQt6 simple help indicator that can be added next to any widget - mirrors Textual TUI."""
    
    help_requested = pyqtSignal()
    
    def __init__(self, help_target: Union[Callable, type] = None,
                 param_name: str = None, param_description: str = None,
                 param_type: type = None, color_scheme: Optional[ColorScheme] = None,
                 scope_accent_color=None, parent=None):
        super().__init__("?", parent)

        # Initialize color scheme
        self.color_scheme = color_scheme or ColorScheme()

        self.help_target = help_target
        self.param_name = param_name
        self.param_description = param_description
        self.param_type = param_type

        # Style as clickable help indicator
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        # CRITICAL: Set initial color - use scope_accent_color if provided, otherwise default
        # NOTE: setStyleSheet must be called AFTER set_scope_accent_color if using scope color
        import logging
        logger = logging.getLogger(__name__)
        if scope_accent_color:
            logger.debug(f"[HELP_INDICATOR] param_name={param_name}, scope_accent_color={scope_accent_color.name()}, RGB=({scope_accent_color.red()},{scope_accent_color.green()},{scope_accent_color.blue()})")
            self.set_scope_accent_color(scope_accent_color)
        else:
            logger.debug(f"[HELP_INDICATOR] param_name={param_name}, using default color")
            # Only set default stylesheet if no scope_accent_color provided
            self.setStyleSheet(f"""
                QLabel {{
                    color: white;
                    font-size: 10px;
                    border: none;
                    border-radius: 3px;
                    padding: 2px 4px;
                    background-color: {self.color_scheme.to_hex(self.color_scheme.selection_bg)};
                }}
                QLabel:hover {{
                    background-color: {self.color_scheme.to_hex(self.color_scheme.selection_bg)};
                }}
            """)
        
        # Set fixed size for consistent appearance (square)
        self.setFixedSize(16, 16)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def showEvent(self, event):
        import logging
        logger = logging.getLogger(__name__)
        parent = self.parentWidget()
        logger.debug(
            "[HELP_INDICATOR] size=%s min=%s max=%s hint=%s parent=%s parent_size=%s",
            self.size(),
            self.minimumSize(),
            self.maximumSize(),
            self.sizeHint(),
            type(parent).__name__ if parent else None,
            parent.size() if parent else None,
        )
        super().showEvent(event)
        
    def set_scope_accent_color(self, color) -> None:
        """Set scope accent color (QColor). Called by parent window for scope styling."""
        from PyQt6.QtGui import QColor

        if not isinstance(color, QColor):
            raise TypeError("HelpIndicator.set_scope_accent_color expects a QColor")

        hex_color = color.name()

        self.setStyleSheet(f"""
            QLabel {{
                color: white;
                font-size: 10px;
                border: none;
                border-radius: 3px;
                padding: 2px 4px;
                background-color: {hex_color};
            }}
            QLabel:hover {{
                background-color: {hex_color};
            }}
        """)

    def mousePressEvent(self, event):
        """Handle mouse press to show help - reuses Textual TUI help manager pattern."""
        if event.button() == Qt.MouseButton.LeftButton:
            try:
                # Import inside method to avoid circular imports (same pattern as Textual TUI)
                from pyqt_reactive.windows.help_window_manager import HelpWindowManager
                import logging
                logger = logging.getLogger(__name__)

                if self.help_target:
                    # Show function/class help using unified manager
                    logger.debug(f"🔍 HelpIndicator clicked: help_target={self.help_target}")
                    HelpWindowManager.show_docstring_help(self.help_target, parent=self)
                elif self.param_name:
                    # Show parameter help using the description passed from parameter analysis
                    logger.debug(f"🔍 HelpIndicator clicked: param_name={self.param_name}, param_description={self.param_description[:50] if self.param_description else 'None'}")
                    HelpWindowManager.show_parameter_help(
                        self.param_name, self.param_description or "No description available", self.param_type, parent=self
                    )

                self.help_requested.emit()

            except Exception as e:
                logger.error(f"Failed to show help: {e}")
                raise

        super().mousePressEvent(event)




class HelpButton(QPushButton):
    """PyQt6 help button for adding help functionality to any widget - mirrors Textual TUI."""

    def __init__(self, help_target: Union[Callable, type] = None,
                 param_name: str = None, param_description: str = None,
                 param_type: type = None, text: str = "Help",
                 color_scheme: Optional[ColorScheme] = None, parent=None,
                 scope_accent_color=None):
        super().__init__(text, parent)

        import logging
        logger = logging.getLogger(__name__)

        # Initialize color scheme
        self.color_scheme = color_scheme or ColorScheme()

        self.help_target = help_target
        self.param_name = param_name
        self.param_description = param_description
        self.param_type = param_type

        # Connect click to help display
        self.clicked.connect(self.show_help)

        # Style as help button
        self._square_icon = text.strip() == "?"
        self._square_size = None
        self._square_width_request = None
        self._square_height_request = None
        self.setMaximumWidth(60)

        # CRITICAL: Use scope_accent_color passed as parameter during creation
        # This ensures help buttons are created with the correct color from the start
        # instead of trying to discover it from parent chain (which doesn't work during __init__)
        fallback_color = self.color_scheme.selection_bg
        initial_color = scope_accent_color or fallback_color

        logger.debug(f"[HELP_BUTTON] __init__: param_name={param_name}, scope_accent_color={scope_accent_color}, fallback_color={fallback_color}, using={initial_color}")

        self._apply_color(initial_color)
        if self._square_icon:
            self._apply_square_constraints(default_size=20)

    def _apply_square_constraints(self, default_size: int | None = None) -> None:
        """Force a square size for icon-style help buttons."""
        if not self._square_icon:
            return
        size = None
        if self._square_width_request and self._square_height_request:
            size = min(self._square_width_request, self._square_height_request)
        elif self._square_width_request:
            size = self._square_width_request
        elif self._square_height_request:
            size = self._square_height_request
        elif default_size is not None:
            size = default_size
        elif self._square_size is not None:
            size = self._square_size

        if size is None:
            return

        self._square_size = size
        super().setMinimumSize(size, size)
        super().setMaximumSize(size, size)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.updateGeometry()

    def setMaximumWidth(self, w: int) -> None:
        super().setMaximumWidth(w)
        if self._square_icon and w and w < 16777215:
            self._square_width_request = w
            self._apply_square_constraints()

    def setMaximumHeight(self, h: int) -> None:
        super().setMaximumHeight(h)
        if self._square_icon and h and h < 16777215:
            self._square_height_request = h
            self._apply_square_constraints()

    def setFixedWidth(self, w: int) -> None:
        super().setFixedWidth(w)
        if self._square_icon and w:
            self._square_width_request = w
            self._apply_square_constraints()

    def setFixedHeight(self, h: int) -> None:
        super().setFixedHeight(h)
        if self._square_icon and h:
            self._square_height_request = h
            self._apply_square_constraints()

    def sizeHint(self) -> QSize:
        if self._square_icon and self._square_size:
            return QSize(self._square_size, self._square_size)
        return super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        if self._square_icon and self._square_size:
            return QSize(self._square_size, self._square_size)
        return super().minimumSizeHint()

    def _get_scope_accent_color(self):
        """Deprecated: retained for compatibility but prefers ScopeColorService.

        Historically HelpButton walked the widget tree to find a parent's
        _scope_accent_color. Prefer using ScopeColorService/get_accent_color by
        scope_id for deterministic behavior. This shim still attempts the old
        lookup as a fallback.
        """
        # Fallback legacy behavior - attempt quick parent attribute lookup
        widget = self.parent()
        depth = 0
        while widget is not None:
            accent_color = getattr(widget, '_scope_accent_color', None)
            if accent_color is not None:
                return accent_color
            if hasattr(widget, 'get_scope_accent_color'):
                try:
                    color = widget.get_scope_accent_color()
                    if color is not None:
                        return color
                except Exception:
                    pass
            widget = widget.parent()
            depth += 1
            if depth > 10:
                break
        return None

    def _apply_color(self, color) -> None:
        """Apply a color to this button (for scope accent styling)."""
        if hasattr(color, 'name'):
            # QColor
            hex_color = color.name()
            hex_lighter = color.lighter(115).name()
            hex_darker = color.darker(115).name()
        else:
            # Tuple or color scheme color
            hex_color = self.color_scheme.to_hex(color)
            hex_lighter = hex_color  # Can't lighten without QColor
            hex_darker = hex_color

        padding = "0" if self._square_icon else "4px 8px"
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {hex_color};
                color: white;
                border: none;
                padding: {padding};
                border-radius: 3px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {hex_lighter};
            }}
            QPushButton:pressed {{
                background-color: {hex_darker};
            }}
        """)

    def set_scope_accent_color(self, color) -> None:
        """Set scope accent color (QColor). Called by parent window for scope styling."""
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"[HELP_BUTTON] set_scope_accent_color CALLED with color={color}")
        self._apply_color(color)

    def show_help(self):
        """Show help using the unified help manager - reuses Textual TUI logic."""
        try:
            # Import inside method to avoid circular imports (same pattern as Textual TUI)
            from pyqt_reactive.windows.help_window_manager import HelpWindowManager
            import logging
            logger = logging.getLogger(__name__)

            logger.info(f"🔍 HelpButton.show_help() CALLED - help_target={self.help_target}, param_name={self.param_name}")
            logger.info(f"🔍 HelpButton parent class: {type(self.parent()).__name__ if self.parent() else 'None'}")
            logger.info(f"🔍 HelpButton parent widget: {self.parent()}")

            if self.help_target:
                # Show function/class help using unified manager
                logger.info(f"🔍 Calling show_docstring_help with target={self.help_target}")
                HelpWindowManager.show_docstring_help(self.help_target, parent=self)
            elif self.param_name:
                # Show parameter help using the description passed from parameter analysis
                logger.info(f"🔍 Calling show_parameter_help with param_name={self.param_name}")
                HelpWindowManager.show_parameter_help(
                    self.param_name, self.param_description or "No description available", self.param_type, parent=self
                )

        except Exception as e:
            logger.error(f"Failed to show help: {e}")
            raise




class ProvenanceLabel(QLabel):
    """QLabel that supports provenance navigation on hover/click.

    When a field inherits its value from an ancestor, hovering shows bold + pointer
    cursor, and clicking navigates to the source window/field.
    """

    def __init__(self, text: str, state=None, dotted_path: str = None, parent=None):
        super().__init__(text, parent)
        self._state = state  # ObjectState instance
        self._dotted_path = dotted_path  # Full dotted path for provenance lookup
        self.setMouseTracking(True)

    def set_provenance_info(self, state, dotted_path: str) -> None:
        """Set provenance info after construction (for deferred binding)."""
        self._state = state
        self._dotted_path = dotted_path

    def _has_provenance(self) -> bool:
        """Check if this field has a provenance source (inherited from ancestor)."""
        if not self._state or not self._dotted_path:
            return False
        try:
            result = self._state.get_provenance(self._dotted_path)
            return result is not None
        except Exception:
            return False

    def enterEvent(self, event) -> None:
        """On hover: show bold + pointer cursor if field has provenance."""
        if self._has_provenance():
            font = self.font()
            font.setBold(True)
            self.setFont(font)
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        """On leave: restore normal font weight."""
        font = self.font()
        font.setBold(False)
        self.setFont(font)
        self.unsetCursor()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        """On click: navigate to provenance source window and field."""
        if event.button() == Qt.MouseButton.LeftButton and self._has_provenance():
            result = self._state.get_provenance(self._dotted_path)
            if result is not None:
                source_scope_id, source_type = result
                self._navigate_to_source(source_scope_id, source_type)
                return
        super().mousePressEvent(event)

    def _navigate_to_source(self, source_scope_id: str, source_type: type) -> None:
        """Open the source window (creating if needed) and scroll to the field.

        Args:
            source_scope_id: The scope where the concrete value exists
            source_type: The TYPE that has the concrete value (may differ from local
                         container type due to MRO inheritance)
        """
        try:
            from pyqt_reactive.services.window_manager import WindowManager

            # Extract field_name from our local dotted path
            field_name = self._dotted_path.split('.')[-1] if '.' in self._dotted_path else self._dotted_path

            logger.debug(f"_navigate_to_source: local_path={self._dotted_path}, field_name={field_name}, "
                        f"source_scope_id={source_scope_id}, source_type={source_type.__name__}")

            # Compute the target path in the source window:
            # We need to find what path source_type is at in the target window's ObjectState
            target_path = self._compute_target_path(source_scope_id, source_type, field_name)

            logger.info(f"🔗 Navigate: {self._dotted_path} → {source_scope_id}::{target_path}")

            # Check if source is in the SAME window (sibling MRO inheritance within same scope)
            current_scope_id = getattr(self._state, 'scope_id', None)
            if current_scope_id == source_scope_id:
                logger.info(f"🔄 Same-window navigation: scrolling to {target_path}")
                self._scroll_within_current_window(target_path)
                return

            # Use the same WindowManager.show_or_focus path as other windows
            from pyqt_reactive.services import WindowFactory

            if WindowManager.is_open(source_scope_id):
                # Window is already open - just focus and navigate, don't move it
                WindowManager.focus_and_navigate(
                    scope_id=source_scope_id,
                    field_path=target_path,
                )
                logger.info(f"✅ Navigated to source: scope={source_scope_id}, path={target_path}")
                return

            def _factory():
                return WindowFactory.create_window_for_scope(source_scope_id)

            window = WindowManager.show_or_focus(source_scope_id, _factory)
            if window:
                window._avoid_widgets = [self.window()] if self.window() else []
                WindowManager.position_window_near_cursor(
                    window,
                    avoid_widgets=[self.window()] if self.window() else None,
                )
                # Navigate to field after window is shown
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(100, lambda: WindowManager.focus_and_navigate(
                    scope_id=source_scope_id,
                    field_path=target_path
                ))
                logger.info(f"✅ Navigated to source: scope={source_scope_id}, path={target_path}")
            else:
                logger.warning(f"Could not create or focus window for scope: {source_scope_id}")

        except Exception as e:
            logger.error(f"Failed to navigate to provenance source: {e}")
            import traceback
            traceback.print_exc()

    def _scroll_within_current_window(self, target_path: str) -> None:
        """Scroll to target_path within the current window (same scope).

        Used for sibling MRO inheritance navigation where source is in same window.
        """
        # Find the window that has ScrollableFormMixin
        current = self.parent()
        while current:
            if hasattr(current, 'select_and_scroll_to_field'):
                current.select_and_scroll_to_field(target_path)
                logger.info(f"✅ Scrolled to {target_path} in current window")
                return
            current = current.parent()

        logger.warning(f"Could not find scrollable parent to navigate to {target_path}")

    def _compute_target_path(self, source_scope_id: str, source_type: type, field_name: str) -> str:
        """Compute the dotted path for source_type.field_name in the target window.

        The source_type might be at a different path in the target window than in our window.
        For example:
        - Local: WellFilterConfig at 'well_filter_config'
        - Source: PathPlanningConfig at 'path_planning_config'

        We need to find what path source_type is at in the target window's ObjectState.

        IMPORTANT: If source_type is ui_hidden (not shown in the UI), we find the closest
        visible subclass in the MRO that also has this field. For example:
        - NapariDisplayConfig is ui_hidden=True
        - NapariStreamingConfig inherits from NapariDisplayConfig and IS visible
        - So we navigate to napari_streaming_config.field instead of napari_display_config.field
        """
        from objectstate import ObjectStateRegistry

        logger.debug(f"_compute_target_path: scope={source_scope_id}, source_type={source_type.__name__}, field={field_name}")

        # Get the target window's ObjectState
        target_state = ObjectStateRegistry.get_by_scope(source_scope_id)
        if target_state is None:
            # Fallback: use same path as local (might work if same type)
            logger.warning(f"No state for scope {source_scope_id}, using local path: {self._dotted_path}")
            return self._dotted_path

        # Debug: log the available types in target state
        logger.debug(f"Target state _path_to_type keys: {list(target_state._path_to_type.keys())}")
        for path, typ in target_state._path_to_type.items():
            if '.' not in path:
                logger.debug(f"  {path} -> {typ.__name__}")

        # Find the path for source_type in the target state
        path_prefix = target_state.find_path_for_type(source_type)
        if path_prefix is None:
            # Fallback: type not found in target - use same path as local
            logger.warning(f"No path for type {source_type.__name__} in scope {source_scope_id}, using local path: {self._dotted_path}")
            return self._dotted_path

        # Check if source_type is ui_hidden - if so, find a visible subclass
        if self._is_type_ui_hidden(source_type):
            visible_path = self._find_visible_subclass_path(
                target_state, source_type, field_name
            )
            if visible_path:
                logger.info(f"UI-hidden fallback: {source_type.__name__} → {visible_path}")
                return visible_path
            # If no visible subclass found, fall through to use original path
            # (scroll will fail but at least we tried)

        # Construct full path: prefix.field_name (empty prefix = root level field)
        target_path = f"{path_prefix}.{field_name}" if path_prefix else field_name
        logger.info(f"Computed target path: {target_path} (source_type={source_type.__name__}, field={field_name})")
        return target_path

    def _is_type_ui_hidden(self, typ: type) -> bool:
        """Check if a type has ui_hidden=True (should not appear in UI forms)."""
        # Check __dict__ directly to avoid inheriting _ui_hidden from parent classes
        return hasattr(typ, '__dict__') and '_ui_hidden' in typ.__dict__ and typ._ui_hidden

    def _find_visible_subclass_path(
        self, target_state, hidden_type: type, field_name: str
    ) -> Optional[str]:
        """Find a visible subclass that inherits from hidden_type and has field_name.

        When provenance points to a ui_hidden config (like NapariDisplayConfig),
        we need to find a visible subclass (like NapariStreamingConfig) that:
        1. Inherits from the hidden type (has it in MRO)
        2. Is visible in the UI (not ui_hidden)
        3. Exists in the target window's ObjectState

        Args:
            target_state: ObjectState of the target window
            hidden_type: The ui_hidden type to find a substitute for
            field_name: The field we want to navigate to

        Returns:
            Full dotted path (e.g., 'napari_streaming_config.colormap') or None
        """
        from objectstate import get_base_type_for_lazy

        # Scan all types in target_state to find visible subclasses
        for path, typ in target_state._path_to_type.items():
            # Skip if path has dots (not a top-level config)
            if '.' in path:
                continue

            # Normalize type for comparison
            typ_base = get_base_type_for_lazy(typ) or typ

            # Skip if this type itself is ui_hidden
            if self._is_type_ui_hidden(typ_base):
                continue

            # Check if hidden_type is in this type's MRO (inheritance chain)
            try:
                mro = typ_base.__mro__
            except AttributeError:
                continue

            hidden_base = get_base_type_for_lazy(hidden_type) or hidden_type
            if hidden_base in mro:
                # Found a visible subclass! Return the path to the field
                target_path = f"{path}.{field_name}"
                logger.debug(f"Found visible subclass: {typ_base.__name__} at path {path}")
                return target_path

        return None

    def _find_main_window(self):
        """Find the main window through the parent chain."""
        current = self.parent()
        while current:
            if hasattr(current, 'floating_windows') and hasattr(current, 'service_adapter'):
                return current
            current = current.parent()
        return None

    # Window creation now handled by WindowFactory.create_window_for_scope()


class LabelWithHelp(QWidget):
    """PyQt6 widget that combines a label with a help indicator - mirrors Textual TUI pattern.

    Uses ProvenanceLabel for the text portion to support click-to-source navigation.
    """

    def __init__(self, text: str, help_target: Union[Callable, type] = None,
                 param_name: str = None, param_description: str = None,
                 param_type: type = None, color_scheme: Optional[ColorScheme] = None,
                 parent=None, state=None, dotted_path: str = None, scope_accent_color=None):
        super().__init__(parent)

        # Transparent background so parent's scope-tinted background shows through
        self.setAutoFillBackground(False)
        self.setStyleSheet("background-color: transparent;")

        # Initialize color scheme
        self.color_scheme = color_scheme or ColorScheme()

        # DEBUG: Log what scope_accent_color was received
        if scope_accent_color:
            logger.debug(f"[LABEL_WITH_HELP] param_name={param_name}, scope_accent_color={scope_accent_color.name()}, RGB=({scope_accent_color.red()},{scope_accent_color.green()},{scope_accent_color.blue()})")
        else:
            logger.debug(f"[LABEL_WITH_HELP] param_name={param_name}, scope_accent_color=None (will use default)")

        # Fixed size policy prevents horizontal stretching
        # This fixes flash area blocking for widgets to the right (e.g., checkbox groups)
        from PyQt6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # Main label - ProvenanceLabel for click-to-source support
        self._base_text = text  # Store base text for dirty indicator toggle
        self._is_dirty = False  # Track dirty state for indicator
        self._label = ProvenanceLabel(text, state=state, dotted_path=dotted_path)
        self._label.setAutoFillBackground(False)  # Transparent so scope background shows through
        layout.addWidget(self._label)

        # Help indicator
        help_indicator = HelpIndicator(
            help_target=help_target,
            param_name=param_name,
            param_description=param_description,
            param_type=param_type,
            color_scheme=self.color_scheme,
            scope_accent_color=scope_accent_color
        )
        layout.addWidget(help_indicator)

        layout.addStretch()

    def set_provenance_info(self, state, dotted_path: str) -> None:
        """Set provenance info (for deferred binding after widget creation)."""
        self._label.set_provenance_info(state, dotted_path)

    def set_underline(self, underline: bool) -> None:
        """Set label underline based on whether value is concrete (not None/placeholder)."""
        font = self._label.font()
        font.setUnderline(underline)
        self._label.setFont(font)

    def set_dirty_indicator(self, is_dirty: bool) -> None:
        """Set dirty indicator (asterisk prefix) for unsaved changes.

        Asterisk (*) means resolved value differs from saved resolved.
        This is orthogonal to underline (which means raw != signature default).
        """
        if is_dirty == self._is_dirty:
            return  # No change needed

        self._is_dirty = is_dirty
        if is_dirty:
            self._label.setText(f"* {self._base_text}")
        else:
            self._label.setText(self._base_text)


class FunctionTitleWithHelp(QWidget):
    """PyQt6 function title with integrated help - mirrors Textual TUI ClickableFunctionTitle."""

    def __init__(self, func: Callable, index: int = None,
                 color_scheme: Optional[ColorScheme] = None, parent=None,
                 scope_accent_color=None):
        super().__init__(parent)

        # Initialize color scheme
        self.color_scheme = color_scheme or ColorScheme()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Function title
        func_name = getattr(func, '__name__', 'Unknown Function')
        module_name = getattr(func, '__module__', '').split('.')[-1] if func else ''

        title = f"{index + 1}: {func_name}" if index is not None else func_name
        if module_name:
            title += f" ({module_name})"

        title_label = QLabel(title)
        title_font = QFont()
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # Help button
        help_btn = HelpButton(help_target=func, text="?", color_scheme=self.color_scheme,
                             scope_accent_color=scope_accent_color, parent=self)
        help_btn.setMaximumWidth(25)
        help_btn.setMaximumHeight(20)
        layout.addWidget(help_btn)

        layout.addStretch()


class GroupBoxWithHelp(FlashableGroupBox):
    """PyQt6 group box with integrated help for dataclass titles - mirrors Textual TUI pattern.

    Inherits from FlashableGroupBox to support smooth flash animations.
    Uses PAINT-TIME color computation via manager.get_flash_color_for_key().
    Supports scope-based borders matching window border patterns.
    """

    # Border patterns matching ScopedBorderMixin
    BORDER_PATTERNS = {
        "solid": (Qt.PenStyle.SolidLine, None),
        "dashed": (Qt.PenStyle.DashLine, [8, 6]),
        "dotted": (Qt.PenStyle.DotLine, [2, 6]),
        "dashdot": (Qt.PenStyle.DashDotLine, [8, 4, 2, 4]),
    }

    def __init__(self, title: str, help_target: Union[Callable, type] = None,
                 color_scheme: Optional[ColorScheme] = None, parent=None,
                 flash_key: str = "", flash_manager=None, scope_accent_color=None):
        super().__init__("", parent, flash_key=flash_key, flash_manager=flash_manager)

        # Initialize color scheme
        self.color_scheme = color_scheme or ColorScheme()
        self.help_target = help_target

        # Ensure stylesheet background actually paints
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)

        # Scope border state (set via set_scope_color_scheme)
        self._scope_color_scheme = None

        # Check if responsive wrapping is enabled
        from pyqt_reactive.widgets.shared.responsive_groupbox_title import is_wrapping_enabled as is_gb_wrapping_enabled
        
        if is_gb_wrapping_enabled():
            # Use responsive title that wraps when narrow
            from pyqt_reactive.widgets.shared.responsive_groupbox_title import ResponsiveGroupBoxTitle
            title_widget = ResponsiveGroupBoxTitle(parent=self, width_threshold=120)
            
            # Title label
            self._title_label = QLabel(title)
            self._title_label.setAutoFillBackground(False)  # Transparent so scope background shows through
            self._base_title = title
            title_font = QFont()
            title_font.setBold(True)
            self._title_label.setFont(title_font)
            title_widget.set_title_widget(self._title_label)
            
            # Help button
            help_btn = None
            if help_target:
                help_btn = HelpButton(
                    help_target=help_target,
                    text="?",
                    color_scheme=self.color_scheme,
                    scope_accent_color=scope_accent_color,
                    parent=self
                )
                help_btn.setMaximumWidth(25)
                help_btn.setMaximumHeight(20)
                title_widget.set_help_widget(help_btn)
            
            self.title_layout = title_widget
        else:
            # Use plain QHBoxLayout (old non-wrapping style)
            title_widget = QWidget()
            # Transparent background so scope-tinted background shows through
            title_widget.setAutoFillBackground(False)
            title_widget.setStyleSheet("background-color: transparent;")
            title_layout = QHBoxLayout(title_widget)
            title_layout.setContentsMargins(0, 0, 0, 0)
            title_layout.setSpacing(5)
            
            # Title label
            self._title_label = QLabel(title)
            self._title_label.setAutoFillBackground(False)  # Transparent so scope background shows through
            self._base_title = title
            title_font = QFont()
            title_font.setBold(True)
            self._title_label.setFont(title_font)
            title_layout.addWidget(self._title_label)
            
            # Help button
            help_btn = None
            if help_target:
                help_btn = HelpButton(
                    help_target=help_target,
                    text="?",
                    color_scheme=self.color_scheme,
                    scope_accent_color=scope_accent_color,
                    parent=self
                )
                help_btn.setMaximumWidth(25)
                help_btn.setMaximumHeight(20)
                title_layout.addWidget(help_btn)
            
            title_layout.addStretch()
            self.title_layout = title_layout

        # Store reference to help button for later insertion
        self._help_button = help_btn

        # Create main layout and add title widget at top
        # Use CURRENT_LAYOUT as single source of truth for margins/spacing
        from pyqt_reactive.forms.layout_constants import CURRENT_LAYOUT
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(*CURRENT_LAYOUT.groupbox_margins)
        main_layout.setSpacing(CURRENT_LAYOUT.groupbox_spacing)
        main_layout.addWidget(title_widget)

        # Content area for child widgets
        self.content_layout = QVBoxLayout()
        main_layout.addLayout(self.content_layout)

    def set_dirty_marker(self, is_dirty: bool, has_sig_diff: bool = False) -> None:
        """Update title styling for dirty (asterisk) and signature diff (underline).

        Two orthogonal visual semantics:
        - Asterisk (*): dirty (resolved_live != resolved_saved)
        - Underline: signature diff (raw != signature default)

        Args:
            is_dirty: True to show asterisk prefix
            has_sig_diff: True to apply underline
        """
        current_text = self._title_label.text()
        has_marker = current_text.startswith("* ")

        if is_dirty and not has_marker:
            self._title_label.setText(f"* {self._base_title}")
        elif not is_dirty and has_marker:
            self._title_label.setText(self._base_title)

        # Apply underline for signature diff (independent of dirty)
        font = self._title_label.font()
        font.setUnderline(has_sig_diff)
        self._title_label.setFont(font)

    def set_scope_color_scheme(self, scheme) -> None:
        """Set scope color scheme for border rendering."""
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(
            "🎨 GroupBoxWithHelp.set_scope_color_scheme: title='%s', scheme=%s, has_scope_parent=%s",
            self.title(),
            scheme is not None,
            self._has_scope_parent()
        )
        logger.debug(
            "🎨 GroupBoxWithHelp.set_scope_color_scheme: objectName=%s stylesheet=%s",
            self.objectName(),
            self.styleSheet()
        )
        self._scope_color_scheme = scheme
        # Avoid double background tint (QGroupBox base bg + scope paint)
        if scheme:
            self.setStyleSheet(
                "QGroupBox { background-color: transparent; border: none; margin-top: 0px; padding-top: 0px; }"
            )
        else:
            self.setStyleSheet("")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        logger.debug(
            "🎨 GroupBoxWithHelp.set_scope_color_scheme: applied stylesheet=%s",
            self.styleSheet()
        )
        # Add margin for border layers if needed
        from pyqt_reactive.widgets.shared.scope_visual_config import ScopeColorScheme

        if isinstance(scheme, ScopeColorScheme) and scheme.step_border_layers:
            total_width = sum(layer[0] for layer in scheme.step_border_layers)
            logger.debug(f"🎨 GroupBoxWithHelp: Setting margins to {total_width} for border layers")
            self.setContentsMargins(total_width, total_width, total_width, total_width)
        self.update()

    def paintEvent(self, event) -> None:
        """Paint with scope background and border layers if set."""
        import logging
        if not getattr(self, "_paint_debug_logged", False):
            logger = logging.getLogger(__name__)
            parent_obj = self.parent()
            logger.debug(
                "[GROUPBOX_PAINT] title='%s' obj_name=%s id=%s rect=%s parent_cls=%s parent_name=%s scope=%s autoFill=%s styled=%s style=%s",
                self._title_label.text() if getattr(self, "_title_label", None) else "",
                self.objectName(),
                id(self),
                self.rect(),
                type(parent_obj).__name__ if parent_obj is not None else None,
                parent_obj.objectName() if parent_obj is not None else None,
                self._scope_color_scheme is not None,
                self.autoFillBackground(),
                self.testAttribute(Qt.WidgetAttribute.WA_StyledBackground),
                self.styleSheet(),
            )
            self._paint_debug_logged = True

        from PyQt6.QtGui import QPainter
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.color_scheme.to_qcolor(self.color_scheme.panel_bg))
        painter.drawRect(self.rect())
        painter.end()

        super().paintEvent(event)

        if not self._scope_color_scheme:
            return

        layers = getattr(self._scope_color_scheme, 'step_border_layers', None)

        # Paint scope background tint (same approach as list item delegate)
        self._paint_scope_background(layers)

        # Paint border layers on top
        if layers:
            self._paint_border_layers(layers)

    def _paint_scope_background(self, layers) -> None:
        """Paint subtle scope-colored background (matching list item style)."""
        from pyqt_reactive.widgets.shared.scope_color_utils import tint_color_perceptual
        from pyqt_reactive.widgets.shared.scope_visual_config import ScopeVisualConfig
        from pyqt_reactive.animation import get_widget_corner_radius, DEFAULT_CORNER_RADIUS

        base_rgb = getattr(self._scope_color_scheme, 'base_color_rgb', None)
        if not base_rgb:
            return

        # Get tint index from first layer (or default)
        if layers:
            _, tint_idx, _ = (layers[0] + ("solid",))[:3]
        else:
            tint_idx = 1

        color = tint_color_perceptual(base_rgb, tint_idx)
        color.setAlphaF(ScopeVisualConfig.GROUPBOX_BG_OPACITY)

        # Get border rect (accounts for margin-top offset)
        rect = self._get_border_rect()

        # Get corner radius for rounded background
        radius = get_widget_corner_radius(self)
        if radius == 0:
            radius = DEFAULT_CORNER_RADIUS

        # Calculate content rect (inside borders)
        border_inset = sum(layer[0] for layer in layers) if layers else 0
        content_rect = rect.adjusted(border_inset, border_inset, -border_inset, -border_inset)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(content_rect), radius - border_inset, radius - border_inset)
        painter.end()

    def _has_scope_parent(self) -> bool:
        """Return True if any parent GroupBoxWithHelp already has scope styling."""
        parent = self.parent()
        while parent is not None:
            if isinstance(parent, GroupBoxWithHelp) and parent._scope_color_scheme:
                return True
            parent = parent.parent()
        return False

    def _get_border_rect(self) -> QRect:
        """Get the painted area rect, accounting for margin-top offset.

        Uses the same geometry calculation as the flash overlay system
        for consistent visual alignment.
        """
        import re
        rect = self.rect()

        # Extract margin-top from stylesheet (same logic as flash overlay)
        margin_top = 0
        stylesheet = self.styleSheet()
        if not stylesheet:
            parent = self.parentWidget()
            while parent:
                stylesheet = parent.styleSheet()
                if stylesheet and 'QGroupBox' in stylesheet:
                    break
                parent = parent.parentWidget()

        if stylesheet:
            match = re.search(r'margin-top\s*:\s*(\d+)', stylesheet)
            if match:
                margin_top = int(match.group(1))

        # Adjust rect to match painted area (offset by margin-top, reduce height)
        return QRect(rect.x(), rect.y() + margin_top, rect.width(), rect.height() - margin_top)

    def _paint_border_layers(self, layers) -> None:
        """Paint layered scope borders (same algorithm as ScopedBorderMixin).

        Uses _get_border_rect() for geometry matching flash overlay.
        """
        from pyqt_reactive.widgets.shared.scope_color_utils import tint_color_perceptual

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Use flash-compatible geometry
        rect = self._get_border_rect()
        inset = 0
        base_rgb = self._scope_color_scheme.base_color_rgb

        # Get corner radius from stylesheet for rounded borders
        from pyqt_reactive.animation import get_widget_corner_radius, DEFAULT_CORNER_RADIUS
        radius = get_widget_corner_radius(self)
        if radius == 0:
            radius = DEFAULT_CORNER_RADIUS

        for layer in layers:
            width, tint_idx, pattern = (layer + ("solid",))[:3]
            color = tint_color_perceptual(base_rgb, tint_idx).darker(120)

            pen = QPen(color, width)
            style, dash_pattern = self.BORDER_PATTERNS.get(
                pattern, self.BORDER_PATTERNS["solid"]
            )
            pen.setStyle(style)
            if dash_pattern:
                pen.setDashPattern(dash_pattern)

            offset = int(inset + width / 2)
            painter.setPen(pen)
            draw_rect = rect.adjusted(offset, offset, -offset - 1, -offset - 1)
            # Draw rounded rect to match flash overlay geometry
            painter.drawRoundedRect(QRectF(draw_rect), radius, radius)
            inset += width

        painter.end()

    def addWidget(self, widget):
        """Add widget to the content area."""
        self.content_layout.addWidget(widget)

    def addLayout(self, layout):
        """Add layout to the content area."""
        self.content_layout.addLayout(layout)

    def addTitleWidget(self, widget):
        """Add widget to the title area, right-aligned (moves to row2 when narrow)."""
        # Add as right widget - will move to second row when narrow
        from pyqt_reactive.widgets.shared.responsive_groupbox_title import ResponsiveGroupBoxTitle
        if isinstance(self.title_layout, ResponsiveGroupBoxTitle):
            self.title_layout.add_right_widget(widget)
        else:
            self.title_layout.addWidget(widget)

    def addTitleInlineWidget(self, widget):
        """Add widget next to the title (stays in row1 always).

        This keeps the widget left-aligned with the title/help button.
        """
        # For responsive title, add inline
        from pyqt_reactive.widgets.shared.responsive_groupbox_title import ResponsiveGroupBoxTitle
        if isinstance(self.title_layout, ResponsiveGroupBoxTitle):
            self.title_layout.add_inline_widget(widget)
        else:
            self.title_layout.addWidget(widget)

    def addTitleWidgetAfterLabel(self, widget):
        """Add widget immediately after the title label."""
        # For responsive title, this adds inline
        from pyqt_reactive.widgets.shared.responsive_groupbox_title import ResponsiveGroupBoxTitle
        if isinstance(self.title_layout, ResponsiveGroupBoxTitle):
            self.title_layout.add_inline_widget(widget)
        else:
            self.title_layout.addWidget(widget)

    def addEnableableWidgets(self, enabled_checkbox, reset_button=None):
        """Add enableable widgets (checkbox + reset) right after help button.

        This is the clean API for adding enableable widgets in the correct position:
        Title → Help → [Enabled Checkbox] → [Reset Button] → Other Controls
        """
        from pyqt_reactive.widgets.shared.responsive_groupbox_title import ResponsiveGroupBoxTitle

        insert_pos = 0
        if self._help_button:
            for i in range(self.title_layout.count()):
                if self.title_layout.itemAt(i).widget() == self._help_button:
                    insert_pos = i + 1
                    break

        if isinstance(self.title_layout, ResponsiveGroupBoxTitle):
            self.title_layout.add_inline_widget(enabled_checkbox)
        else:
            self.title_layout.insertWidget(insert_pos, enabled_checkbox)

        if reset_button:
            if not reset_button.styleSheet():
                reset_button.setStyleSheet(
                    f"background-color: {self.color_scheme.to_hex(self.color_scheme.button_normal_bg)};"
                )
            if isinstance(self.title_layout, ResponsiveGroupBoxTitle):
                self.title_layout.add_inline_widget(reset_button)
            else:
                insert_pos += 1
                if self.title_layout.count() > 0 and self.title_layout.itemAt(self.title_layout.count() - 1).spacerItem():
                    self.title_layout.insertWidget(self.title_layout.count() - 1, reset_button)
                else:
                    self.title_layout.insertWidget(insert_pos, reset_button)
