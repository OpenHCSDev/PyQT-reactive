"""
Widget creation configuration - parametric pattern.

Single source of truth for widget creation behavior (REGULAR, NESTED, and OPTIONAL_NESTED).
Mirrors the framework_config pattern.

Architecture:
- Widget handlers: Custom logic for complex operations
- Unified config: Single _WIDGET_CREATION_CONFIG dict with all metadata
- Parametric dispatch: Handlers are typed callables (no eval strings)

All three widget types (REGULAR, NESTED, OPTIONAL_NESTED) are now parametrized.
OPTIONAL_NESTED reuses the same nested form creation logic as NESTED, with additional
handlers for checkbox title widget and None/instance toggle logic.
"""

from enum import Enum
import logging
import itertools

logger = logging.getLogger(__name__)
from typing import Any, Callable, Optional, Type, Tuple
import logging

from .widget_creation_types import (
    ParameterFormManager, ParameterInfo, DisplayInfo, FieldIds,
    WidgetCreationConfig
)
from pyqt_reactive.services.field_change_dispatcher import FieldChangeDispatcher, FieldChangeEvent
from pyqt_reactive.services.widget_service import WidgetService
from pyqt_reactive.widgets.shared.responsive_layout_widgets import ResponsiveParameterRow
from pyqt_reactive.forms.layout_constants import CURRENT_LAYOUT

logger = logging.getLogger(__name__)
_WIDGET_CREATE_SEQ = itertools.count(1)


class WidgetCreationType(Enum):
    """
    Enum for widget creation strategies - mirrors MemoryType pattern.

    PyQt6 uses 3 parametric types: REGULAR, NESTED, and OPTIONAL_NESTED.
    """
    REGULAR = "regular"
    NESTED = "nested"
    OPTIONAL_NESTED = "optional_nested"


# ============================================================================
# WIDGET CREATION HANDLERS - Special-case logic (like framework handlers)
# ============================================================================

def _unwrap_optional_type(param_type: Type) -> Type:
    """Unwrap Optional[T] to get T."""
    from .parameter_type_utils import ParameterTypeUtils
    return (
        ParameterTypeUtils.get_optional_inner_type(param_type)
        if ParameterTypeUtils.is_optional_dataclass(param_type)
        else param_type
    )


def _create_optimized_reset_button(field_id: str, param_name: str, reset_callback):
    """
    Optimized reset button factory - reuses configuration to save ~0.15ms per button.

    This factory creates reset buttons with consistent styling and configuration,
    avoiding repeated property setting overhead.
    """
    from PyQt6.QtWidgets import QPushButton

    button = QPushButton("Reset")
    button.setObjectName(f"{field_id}_reset")
    button.setMaximumWidth(60)  # Standard reset button width
    button.setFixedHeight(CURRENT_LAYOUT.button_height)
    button.clicked.connect(reset_callback)
    return button


def _apply_reset_button_style(button, color_scheme) -> None:
    """Apply the canonical reset button style (SSOT)."""
    button.setStyleSheet(
        f"""
        QPushButton {{
            background-color: {color_scheme.to_hex(color_scheme.button_normal_bg)};
            border: none;
            border-radius: 3px;
            padding: 2px 6px;
            font-size: 11px;
        }}
        QPushButton:hover {{
            background-color: {color_scheme.to_hex(color_scheme.button_hover_bg)};
        }}
        QPushButton:pressed {{
            background-color: {color_scheme.to_hex(color_scheme.button_pressed_bg)};
        }}
        """
    )


def _create_nested_form(manager, param_info, display_info, field_ids, current_value, unwrapped_type, layout=None, CURRENT_LAYOUT=None, QWidget=None, GroupBoxWithHelp=None, PyQt6ColorScheme=None) -> Any:
    """
    Handler for creating nested form.

    NOTE: This creates the nested manager AND stores it in manager.nested_managers.
    The caller should NOT try to store it again.

    Extra parameters (layout, CURRENT_LAYOUT, etc.) are accepted but not used - they're
    part of the unified handler signature for consistency.
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.debug(f"🔍 _create_nested_form: ENTRY - param_name={param_info.name}, unwrapped_type={unwrapped_type}")
    nested_manager = manager._create_nested_form_inline(
        param_info.name, unwrapped_type, current_value
    )
    # Store nested manager BEFORE building form (needed for reset button connection)
    manager.nested_managers[param_info.name] = nested_manager
    logger.debug(f"🔍 _create_nested_form: stored in manager.nested_managers['{param_info.name}']")
    # For enableable types: Move enabled widget to title after form is built
    from python_introspect import ENABLED_FIELD, is_enableable
    if is_enableable(unwrapped_type):
        logger.debug(f"🔍 _create_nested_form: Registering callback to move enabled widget for {param_info.name}")
        logger.debug(f"🔍 _create_nested_form: nested_manager._on_build_complete_callbacks count BEFORE: {len(nested_manager._on_build_complete_callbacks)}")

        # Register callback to move enabled widget AND apply initial styling
        def on_build_complete():
            import logging
            log = logging.getLogger(__name__)
            log.debug(f"[BUILD_COMPLETE] FIRED for {nested_manager.field_id}, widget_count={len(nested_manager.widgets)}, widgets={list(nested_manager.widgets.keys())}")

            _move_enabled_widget_to_title(nested_manager, manager, param_info.name, ENABLED_FIELD)

            log.debug(f"[BUILD_COMPLETE] After move_enabled_widget: enabled_widget exists={'enabled' in nested_manager.widgets}, widget_count={len(nested_manager.widgets)}")

            # After enabled widget is moved, apply initial enabled styling
            if 'enabled' in nested_manager.parameters:
                log.debug(f"[BUILD_COMPLETE] Applying initial enabled styling to {nested_manager.field_id}")
                nested_manager._enabled_field_styling_service.apply_initial_enabled_styling(nested_manager)

            # NOTE: Scope accent color is already applied during widget creation via scope_accent_color parameter
            # No need to discover and re-apply it here

        nested_manager._on_build_complete_callbacks.append(on_build_complete)
        logger.debug(f"🔍 _create_nested_form: nested_manager._on_build_complete_callbacks count AFTER: {len(nested_manager._on_build_complete_callbacks)}")

    logger.debug(f"🔍 _create_nested_form: Calling build_form() for {nested_manager.field_id}")
    result = nested_manager.build_form()
    logger.debug(f"🔍 _create_nested_form: build_form() returned for {nested_manager.field_id}, widgets={len(nested_manager.widgets)}")
    return result


def _move_enabled_widget_to_title(nested_manager, parent_manager, nested_param_name: str, enabled_field: str) -> None:
    """
    Move the enabled widget from its normal form row to the GroupBoxWithHelp title.

    This allows the enabled field to go through normal widget creation (gets proper widget_id,
    widgets dict registration, reset button, placeholder syncing) but just changes
    its visual placement to the title area.

    The enabled checkbox is placed after the title label and help button in the title layout.
    """
    import logging
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QWidget, QLabel
    from pyqt_reactive.widgets.no_scroll_spinbox import NoneAwareCheckBox

    logger = logging.getLogger(__name__)
    logger.debug(f"🔍 _move_enabled_widget_to_title: enabled_field={enabled_field}, nested_param_name={nested_param_name}")
    logger.debug(f"🔍 _move_enabled_widget_to_title: nested_manager.widgets keys={list(nested_manager.widgets.keys())}")
    if hasattr(parent_manager, "widgets"):
        logger.debug(f"🔍 _move_enabled_widget_to_title: parent_manager.widgets keys={list(parent_manager.widgets.keys())}")

    if enabled_field not in nested_manager.widgets:
        logger.warning(f"⚠️  _move_enabled_widget_to_title: enabled_field '{enabled_field}' not in nested_manager.widgets")
        return

    enabled_widget = nested_manager.widgets[enabled_field]
    enabled_reset_button = nested_manager.reset_buttons.get(enabled_field)

    logger.debug(f"🔍 _move_enabled_widget_to_title: found enabled_widget={enabled_widget}, enabled_reset_button={enabled_reset_button}")

    # Find the container (GroupBoxWithHelp) for the nested form
    from pyqt_reactive.widgets.shared.clickable_help_components import GroupBoxWithHelp
    container = parent_manager.widgets.get(nested_param_name) if hasattr(parent_manager, "widgets") else None
    if not isinstance(container, GroupBoxWithHelp):
        # Function pane case: parent_manager *is* the container
        if hasattr(parent_manager, "addEnableableWidgets") and hasattr(parent_manager, "_title_label"):
            container = parent_manager
        else:
            logger.warning(f"⚠️  _move_enabled_widget_to_title: container '{nested_param_name}' not found or not a GroupBoxWithHelp")
            return

    logger.debug(f"🔍 _move_enabled_widget_to_title: found container with title_layout")

    # Find the row layout that contains the enabled widget
    enabled_widget_parent = enabled_widget.parent()
    if not enabled_widget_parent:
        logger.warning(f"⚠️  _move_enabled_widget_to_title: enabled_widget has no parent")
        return

    # Find the enabled widget's layout and remove the row
    enabled_widget_layout = enabled_widget_parent.layout()
    if not enabled_widget_layout:
        logger.warning(f"⚠️  _move_enabled_widget_to_title: enabled_widget parent has no layout")
        return

    logger.debug(f"🔍 _move_enabled_widget_to_title: removing enabled widget from row layout")

    # Remove the label (which contains the help button) from the row layout
    enabled_label = nested_manager.labels.get(enabled_field)
    if enabled_label:
        enabled_widget_layout.removeWidget(enabled_label)
        enabled_label.hide()  # Hide the label so it's not visible
        logger.debug(f"🔍 _move_enabled_widget_to_title: removed and hidden label with help button from row layout")

    # Remove the enabled widget from the row layout
    enabled_widget_layout.removeWidget(enabled_widget)

    # Remove the enabled reset button from the row layout if it exists
    if enabled_reset_button:
        enabled_widget_layout.removeWidget(enabled_reset_button)
        logger.debug(f"🔍 _move_enabled_widget_to_title: removed reset button from row layout")

    # Find the title label in the container and make it clickable
    title_label = container._title_label
    logger.debug(f"🔍 _move_enabled_widget_to_title: using container._title_label={title_label}")

    # Keep reference to original checkbox for toggle functionality
    checkbox_widget = enabled_widget

    # Wrap checkbox in container with background color to match form row appearance
    if isinstance(enabled_widget, NoneAwareCheckBox):
        from PyQt6.QtWidgets import QWidget, QHBoxLayout, QStyle
        from PyQt6.QtCore import Qt
        bg_color = parent_manager.color_scheme.to_hex(parent_manager.color_scheme.button_normal_bg)
        checkbox_container = QWidget()
        checkbox_container.setStyleSheet(f"background-color: {bg_color};")
        indicator_w = enabled_widget.style().pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth)
        indicator_h = enabled_widget.style().pixelMetric(QStyle.PixelMetric.PM_IndicatorHeight)
        checkbox_container.setFixedSize(indicator_w, indicator_h)
        layout = QHBoxLayout(checkbox_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        enabled_widget.setStyleSheet("padding: 0px; margin: 0px;")
        enabled_widget.setFixedSize(indicator_w, indicator_h)
        enabled_widget.setParent(checkbox_container)
        layout.addWidget(enabled_widget)
        enabled_widget = checkbox_container
        logger.debug(f"🔍 _move_enabled_widget_to_title: wrapped checkbox in background container")

    # Make title clickable to toggle enabled checkbox
    if title_label and isinstance(checkbox_widget, NoneAwareCheckBox):
        def on_title_click(e):
            checkbox_widget.toggle()
            # Ensure checkmark color is correct (white in dark mode)
            checkbox_widget._apply_concrete_palette()
        title_label.mousePressEvent = on_title_click
        title_label.setCursor(Qt.CursorShape.PointingHandCursor)
        logger.debug(f"🔍 _move_enabled_widget_to_title: made title_label clickable")

    logger.debug(f"🔍 _move_enabled_widget_to_title: adding enabled widget to title_layout (count={container.title_layout.count()})")

    if enabled_reset_button is not None:
        _apply_reset_button_style(enabled_reset_button, parent_manager.color_scheme)
        enabled_reset_button.setMaximumWidth(60)
        enabled_reset_button.setFixedHeight(CURRENT_LAYOUT.button_height)

    # Create provenance navigation button
    from pyqt_reactive.widgets.shared.clickable_help_components import ProvenanceButton

    # Compute dotted path for enabled field
    dotted_path = f'{nested_manager.field_id}.{enabled_field}' if nested_manager.field_id else enabled_field

    # Create and configure provenance button
    provenance_button = ProvenanceButton(
        text="^",
        color_scheme=parent_manager.color_scheme
    )
    provenance_button.setMaximumWidth(25)
    provenance_button.setFixedHeight(CURRENT_LAYOUT.button_height)

    # Apply same styling as reset button (hover/pressed states)
    _apply_reset_button_style(provenance_button, parent_manager.color_scheme)

    # Set provenance info for navigation
    provenance_button.set_provenance_info(nested_manager.state, dotted_path)

    # Update button visibility based on whether provenance is actually available
    has_provenance = provenance_button._has_provenance()
    logger.debug(f"🔍 _move_enabled_widget_to_title: dotted_path={dotted_path}, has_provenance={has_provenance}")
    provenance_button.update_visibility_based_on_provenance()

    # Underline checkbox if enabled field's value differs from signature
    should_underline = dotted_path in nested_manager.state.signature_diff_fields
    logger.debug(f"🔍 _move_enabled_widget_to_title: should_underline={should_underline}, signature_diff_fields={nested_manager.state.signature_diff_fields}")
    if should_underline and isinstance(checkbox_widget, NoneAwareCheckBox):
        font = checkbox_widget.font()
        font.setUnderline(True)
        checkbox_widget.setFont(font)
        logger.debug(f"🔍 _move_enabled_widget_to_title: underlined checkbox_widget for signature diff")

    container.addEnableableWidgets(enabled_widget, enabled_reset_button, provenance_button)
    logger.debug(f"🔍 _move_enabled_widget_to_title: added widgets to container, provenance_button visible={provenance_button.isVisible()}")

    # Clean up the empty row layout if possible
    if enabled_widget_layout.count() == 0:
        # Remove the empty row from its parent
        row_parent = enabled_widget_layout.parent()
        if isinstance(row_parent, QWidget):
            row_parent.setParent(None)
            logger.debug(f"🔍 _move_enabled_widget_to_title: removed empty row parent")

    logger.debug(f"🔍 _move_enabled_widget_to_title: COMPLETE")


def _create_optional_title_widget(manager, param_info, display_info, field_ids, current_value, unwrapped_type):
    """
    Handler for creating optional dataclass title widget with checkbox.

    Creates: checkbox + title label + reset button + help button (all inline).
    Returns: (title_widget, checkbox) tuple for later connection.
    """
    from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont
    from pyqt_reactive.widgets.no_scroll_spinbox import NoneAwareCheckBox
    from pyqt_reactive.widgets.shared.clickable_help_components import HelpButton
    from pyqt_reactive.forms.layout_constants import CURRENT_LAYOUT

    title_widget = QWidget()
    title_layout = QHBoxLayout(title_widget)
    title_layout.setSpacing(CURRENT_LAYOUT.parameter_row_spacing)
    title_layout.setContentsMargins(*CURRENT_LAYOUT.parameter_row_margins)

    # Checkbox (compact, no text)
    checkbox = NoneAwareCheckBox()
    checkbox.setObjectName(field_ids['optional_checkbox_id'])
    # Title checkbox ONLY controls None vs Instance, NOT the enabled field
    checkbox.setChecked(current_value is not None)
    checkbox.setMaximumWidth(20)
    title_layout.addWidget(checkbox)

    # Title label (clickable to toggle checkbox)
    title_label = QLabel(display_info['checkbox_label'])
    title_font = QFont()
    title_font.setBold(True)
    title_label.setFont(title_font)
    title_label.mousePressEvent = lambda e: checkbox.toggle()
    title_label.setCursor(Qt.CursorShape.PointingHandCursor)
    title_layout.addWidget(title_label)

    # CRITICAL: Use scope_accent_color from manager config (passed from parent window)
    # No need to walk parent chain - it's stored directly in the manager
    scope_accent_color = getattr(manager, '_scope_accent_color', None)

    # Help button (immediately to the right of the title)
    help_btn = HelpButton(help_target=unwrapped_type, text="?", color_scheme=manager.color_scheme,
                         scope_accent_color=scope_accent_color, parent=title_widget)
    help_btn.setMaximumWidth(25)
    help_btn.setFixedHeight(CURRENT_LAYOUT.button_height)
    title_layout.addWidget(help_btn)

    title_layout.addStretch()

    # Reset All button (right-aligned)
    reset_all_button = None
    if not manager.read_only:
        reset_all_button = QPushButton("Reset")
        reset_all_button.setMaximumWidth(60)
        reset_all_button.setFixedHeight(CURRENT_LAYOUT.button_height)
        reset_all_button.setToolTip(f"Reset all parameters in {display_info['checkbox_label']} to defaults")
        _apply_reset_button_style(reset_all_button, manager.color_scheme)
        title_layout.addWidget(reset_all_button)

    return {
        'title_widget': title_widget,
        'checkbox': checkbox,
        'title_label': title_label,
        'help_btn': help_btn,
        'reset_all_button': reset_all_button,
    }


def _connect_optional_checkbox_logic(manager, param_info, checkbox, nested_form, nested_manager, title_label, help_btn, unwrapped_type):
    """
    Handler for connecting optional dataclass checkbox toggle logic.

    Checkbox controls None vs instance state (independent of enabled field).
    """
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QGraphicsOpacityEffect

    def on_checkbox_changed(checked):
        # Title checkbox controls whether config exists (None vs instance)
        nested_form.setEnabled(checked)

        if checked:
            # Config exists - create instance preserving the enabled field value
            current_param_value = manager.parameters.get(param_info.name)
            if current_param_value is None:
                # Create new instance with default enabled value
                new_instance = unwrapped_type()
                manager.update_parameter(param_info.name, new_instance)

            # Remove dimming for None state (title only)
            title_label.setStyleSheet("")
            help_btn.setEnabled(True)

            # Trigger the nested config's enabled handler to apply enabled styling
            # CRITICAL FIX: Call the service method, not a non-existent manager method
            QTimer.singleShot(0, lambda: nested_manager._enabled_field_styling_service.apply_initial_enabled_styling(nested_manager))
        else:
            # Config is None - set to None and block inputs
            manager.update_parameter(param_info.name, None)

            # Apply dimming for None state
            title_label.setStyleSheet(f"color: {manager.color_scheme.to_hex(manager.color_scheme.text_disabled)};")
            help_btn.setEnabled(True)
            # ANTI-DUCK-TYPING: Use ABC-based widget discovery
            for widget in manager._widget_ops.get_all_value_widgets(nested_form):
                effect = QGraphicsOpacityEffect()
                effect.setOpacity(0.4)
                widget.setGraphicsEffect(effect)

    checkbox.toggled.connect(on_checkbox_changed)

    # Register callback for initial styling (deferred until after all widgets are created)
    def apply_initial_styling():
        on_checkbox_changed(checkbox.isChecked())

    manager._on_build_complete_callbacks.append(apply_initial_styling)


def _create_regular_container(manager: ParameterFormManager, param_info: ParameterInfo,
                             display_info: DisplayInfo, field_ids: FieldIds, current_value: Any,
                             unwrapped_type: Optional[Type], layout=None, CURRENT_LAYOUT=None,
                             QWidget=None, GroupBoxWithHelp=None, PyQt6ColorScheme=None) -> Any:
    """Create container for REGULAR widget type."""
    from pyqt_reactive.widgets.shared.responsive_layout_widgets import (
        ResponsiveParameterRow, is_wrapping_enabled as is_row_wrapping_enabled
    )
    
    # Use parent from manager if available
    parent = getattr(manager, 'parent', lambda: None)()
    
    # Check if responsive wrapping is enabled
    if is_row_wrapping_enabled():
        # Use responsive row that wraps when narrow
        container = ResponsiveParameterRow(
            width_threshold=150, 
            parent=parent,
            layout_config=CURRENT_LAYOUT
        )
    else:
        # Use plain QWidget with QHBoxLayout (old non-wrapping style)
        from PyQt6.QtWidgets import QWidget as QtWidget
        container = QtWidget(parent)

    return container


def _create_nested_container(manager: ParameterFormManager, param_info: ParameterInfo,
                            display_info: DisplayInfo, field_ids: FieldIds, current_value: Any,
                            unwrapped_type: Optional[Type], layout=None, CURRENT_LAYOUT=None,
                            QWidget=None, GroupBoxWithHelp=None, PyQt6ColorScheme=None) -> Any:
    """Create container for NESTED widget type."""
    from pyqt_reactive.widgets.shared.clickable_help_components import GroupBoxWithHelp as GBH
    from pyqt_reactive.theming.color_scheme import ColorScheme as PCS
    from pyqt_reactive.forms.form_init_service import FormBuildOrchestrator

    color_scheme = manager.config.color_scheme or PCS()
    # Get root manager for flash - nested managers share root's _flash_colors dict
    root_manager = manager
    while getattr(root_manager, '_parent_manager', None) is not None:
        root_manager = root_manager._parent_manager
    # Flash keys must identify the *section* via a canonical dotted path.
    # Example: "processing_config.path_planning_config" (not just "path_planning_config").
    flash_key = f"{manager.field_id}.{param_info.name}" if manager.field_id else param_info.name

    # CRITICAL: Use scope_accent_color from manager config (passed from parent window)
    # No need to walk parent chain - it's stored directly in the manager
    scope_accent_color = getattr(manager, '_scope_accent_color', None)

    import logging
    logger = logging.getLogger(__name__)
    logger.debug(f"[CREATE_NESTED] field_id={manager.field_id}, manager._scope_accent_color={scope_accent_color}")
    logger.debug(
        "[CREATE_NESTED] param=%s title=%s widget=GroupBoxWithHelp",
        param_info.name,
        display_info.get('field_label')
    )

    container = GBH(
        title=display_info['field_label'],
        help_target=unwrapped_type,
        color_scheme=color_scheme,
        scope_accent_color=scope_accent_color,  # Pass scope accent color
        flash_key=flash_key,
        flash_manager=root_manager
    )
    return container


def _create_optional_nested_container(manager: ParameterFormManager, param_info: ParameterInfo,
                                     display_info: DisplayInfo, field_ids: FieldIds, current_value: Any,
                                     unwrapped_type: Optional[Type], layout=None, CURRENT_LAYOUT=None,
                                     QWidget=None, GroupBoxWithHelp=None, PyQt6ColorScheme=None) -> Any:
    """Create container for OPTIONAL_NESTED widget type."""
    from PyQt6.QtWidgets import QGroupBox
    from PyQt6.QtGui import QPalette
    from pyqt_reactive.theming.color_scheme import ColorScheme as PCS
    import logging

    color_scheme = manager.config.color_scheme or PCS()
    container = QGroupBox()
    palette = container.palette()
    palette.setColor(QPalette.ColorRole.Window, color_scheme.to_qcolor(color_scheme.panel_bg))
    container.setPalette(palette)
    container.setAutoFillBackground(True)
    logger = logging.getLogger(__name__)
    logger.debug(
        "[OPTIONAL_NESTED] Created QGroupBox: name=%s title=%s autoFill=%s palette_window=%s",
        field_ids.get('widget_id'),
        display_info.get('field_label'),
        container.autoFillBackground(),
        palette.color(QPalette.ColorRole.Window).name()
    )
    return container


def _setup_regular_layout(manager: ParameterFormManager, param_info: ParameterInfo,
                         display_info: DisplayInfo, field_ids: FieldIds, current_value: Any,
                         unwrapped_type: Optional[Type], container=None, CURRENT_LAYOUT=None,
                         QWidget=None, GroupBoxWithHelp=None, PyQt6ColorScheme=None) -> None:
    """Setup layout for REGULAR widget type.

    For REGULAR widgets, container is a QWidget with a layout already set.
    We need to configure the layout, not the container.
    
    If container is ResponsiveParameterRow, it manages its own layout so we skip setup.
    """
    # Skip layout setup for ResponsiveParameterRow - it manages its own layout
    if isinstance(container, ResponsiveParameterRow):
        return
    
    layout = container.layout()
    # QLayout.__bool__ returns False even when the layout exists, so we do not
    # use a truthiness check here. For REGULAR rows we *require* that a layout
    # has already been set (create_widget_parametric installs a QHBoxLayout),
    # so if this ever ends up being None it's a programmer error and should
    # raise loudly.
    layout.setSpacing(CURRENT_LAYOUT.parameter_row_spacing)
    layout.setContentsMargins(*CURRENT_LAYOUT.parameter_row_margins)


def _setup_optional_nested_layout(manager: ParameterFormManager, param_info: ParameterInfo,
                                 display_info: DisplayInfo, field_ids: FieldIds, current_value: Any,
                                 unwrapped_type: Optional[Type], container=None, CURRENT_LAYOUT=None,
                                 QWidget=None, GroupBoxWithHelp=None, PyQt6ColorScheme=None) -> None:
    """Setup layout for OPTIONAL_NESTED widget type."""
    from PyQt6.QtWidgets import QVBoxLayout as QVL
    container.setLayout(QVL())
    container.layout().setSpacing(0)
    container.layout().setContentsMargins(0, 0, 0, 0)


# ============================================================================
# UNIFIED WIDGET CREATION CONFIGURATION (typed, no eval strings)
# ============================================================================

_WIDGET_CREATION_CONFIG: dict[WidgetCreationType, WidgetCreationConfig] = {
    WidgetCreationType.REGULAR: WidgetCreationConfig(
        layout_type='QHBoxLayout',
        is_nested=False,
        create_container=_create_regular_container,
        setup_layout=_setup_regular_layout,
        create_main_widget=lambda manager, param_info, display_info, field_ids, current_value, unwrapped_type, *args, **kwargs:
            manager._widget_creator(param_info.name, param_info.type, current_value, field_ids['widget_id'], None),
        needs_label=True,
        needs_reset_button=True,
        needs_unwrap_type=False,
    ),

    WidgetCreationType.NESTED: WidgetCreationConfig(
        layout_type='GroupBoxWithHelp',
        is_nested=True,
        create_container=_create_nested_container,
        setup_layout=None,
        create_main_widget=_create_nested_form,
        needs_label=False,
        needs_reset_button=True,
        needs_unwrap_type=True,
        is_optional=False,
    ),

    WidgetCreationType.OPTIONAL_NESTED: WidgetCreationConfig(
        layout_type='QGroupBox',
        is_nested=True,
        create_container=_create_optional_nested_container,
        setup_layout=_setup_optional_nested_layout,
        create_main_widget=_create_nested_form,
        needs_label=False,
        needs_reset_button=True,
        needs_unwrap_type=True,
        is_optional=True,
        needs_checkbox=True,
        create_title_widget=_create_optional_title_widget,
        connect_checkbox_logic=_connect_optional_checkbox_logic,
    ),
}


# ============================================================================
# WIDGET OPERATIONS - Direct access to typed config (no eval)
# ============================================================================

def _get_widget_operations(creation_type: WidgetCreationType) -> dict[str, Callable]:
    """Get typed widget operations for a creation type."""
    config = _WIDGET_CREATION_CONFIG[creation_type]
    ops = {
        'create_container': config.create_container,
        'create_main_widget': config.create_main_widget,
    }
    if config.setup_layout:
        ops['setup_layout'] = config.setup_layout
    if config.create_title_widget:
        ops['create_title_widget'] = config.create_title_widget
    if config.connect_checkbox_logic:
        ops['connect_checkbox_logic'] = config.connect_checkbox_logic
    return ops


# ============================================================================
# UNIFIED WIDGET CREATION FUNCTION
# ============================================================================

def create_widget_parametric(manager: ParameterFormManager, param_info: ParameterInfo) -> Any:
    """
    UNIFIED: Create widget using parametric dispatch.

    Widget type is determined by param_info.widget_creation_type attribute.
    """
    from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QPushButton
    from pyqt_reactive.widgets.shared.clickable_help_components import GroupBoxWithHelp, LabelWithHelp
    from pyqt_reactive.forms.widget_strategies import PyQt6WidgetEnhancer
    from pyqt_reactive.theming.color_scheme import ColorScheme as PyQt6ColorScheme
    from pyqt_reactive.forms.layout_constants import CURRENT_LAYOUT
    import logging

    logger = logging.getLogger(__name__)

    # Type declares its own widget creation strategy
    creation_type = WidgetCreationType[param_info.widget_creation_type]

    # Get config and operations for this type
    config = _WIDGET_CREATION_CONFIG[creation_type]
    ops = _get_widget_operations(creation_type)

    # Prepare context
    display_info = WidgetService.get_parameter_display_info(
        param_info.name, param_info.type, manager=manager, description=param_info.description
    )
    field_ids = manager.service.generate_field_ids_direct(manager.config.field_id, param_info.name)
    current_value = manager.parameters.get(param_info.name)
    unwrapped_type = _unwrap_optional_type(param_info.type) if config.needs_unwrap_type else None

    # DEBUG: Show what config is selected
    import logging
    logger = logging.getLogger(__name__)
    logger.debug(f"🔍 create_widget_parametric: config type = {type(config).__name__}, is_nested={config.is_nested}, is_optional={config.is_optional}")

    # Execute operations
    container = ops['create_container'](
        manager, param_info, display_info, field_ids, current_value, unwrapped_type,
        None, CURRENT_LAYOUT, QWidget, GroupBoxWithHelp, PyQt6ColorScheme
    )
    create_seq = next(_WIDGET_CREATE_SEQ)
    try:
        parent_obj = container.parent() if container is not None else None
        logger.debug(
            "[WIDGET_CREATE] seq=%s stage=container type=%s param=%s field_id=%s manager_seq=%s container_cls=%s obj_name=%s id=%s parent_cls=%s",
            create_seq,
            creation_type.value,
            param_info.name,
            manager.config.field_id,
            getattr(manager, "_pfm_seq", None),
            type(container).__name__ if container is not None else None,
            container.objectName() if container is not None else None,
            id(container) if container is not None else None,
            type(parent_obj).__name__ if parent_obj is not None else None,
        )
    except Exception:
        logger.debug("[WIDGET_CREATE] seq=%s stage=container param=%s log_failed", create_seq, param_info.name)

    # GAME ENGINE: Register groupbox with overlay for flash rendering
    # Only for nested containers (GroupBoxWithHelp) that have flash_key
    if config.is_nested and hasattr(container, '_flash_key'):
        flash_key = container._flash_key
        # Get root manager for overlay registration
        root_manager = manager
        while getattr(root_manager, '_parent_manager', None) is not None:
            root_manager = root_manager._parent_manager
        if hasattr(root_manager, 'register_flash_groupbox'):
            root_manager.register_flash_groupbox(flash_key, container)

    # Apply scope color scheme to nested containers for proper background/border styling
    if config.is_nested and isinstance(container, GroupBoxWithHelp):
        # Get scope color scheme from manager or root manager
        scope_color_scheme = getattr(manager, '_scope_color_scheme', None)
        if scope_color_scheme is None:
            # Try to get from root manager
            root_manager = manager
            while getattr(root_manager, '_parent_manager', None) is not None:
                root_manager = root_manager._parent_manager
            scope_color_scheme = getattr(root_manager, '_scope_color_scheme', None)
        
        if scope_color_scheme:
            container.set_scope_color_scheme(scope_color_scheme)

    # Setup layout - polymorphic dispatch
    # Each setup_layout function handles its own container type
    layout_type = config.layout_type
    if layout_type == 'QHBoxLayout':
        # Check if container is ResponsiveParameterRow - it manages its own layout
        if isinstance(container, ResponsiveParameterRow):
            layout = None  # ResponsiveParameterRow manages its own layout
        else:
            layout = QHBoxLayout(container)
    elif layout_type == 'QVBoxLayout':
        layout = QVBoxLayout(container)
    elif layout_type == 'QGroupBox':
        layout = None  # Will be set by setup_layout
    else:  # GroupBoxWithHelp
        layout = container.layout()

    if ops.get('setup_layout'):
        # Polymorphic dispatch: each setup_layout function handles its container type
        ops['setup_layout'](
            manager, param_info, display_info, field_ids, current_value, unwrapped_type,
            container, CURRENT_LAYOUT, QWidget, GroupBoxWithHelp, PyQt6ColorScheme
        )
        # For OPTIONAL_NESTED, get the layout after setup
        if layout_type == 'QGroupBox':
            layout = container.layout()

    # Add title widget if needed (OPTIONAL_NESTED only)
    title_components = None
    if config.is_optional:
        title_components = ops['create_title_widget'](
            manager, param_info, display_info, field_ids, current_value, unwrapped_type
        )
        layout.addWidget(title_components['title_widget'])
        try:
            title_widget = title_components.get('title_widget') if title_components else None
            checkbox = title_components.get('checkbox') if title_components else None
            reset_btn = title_components.get('reset_all_button') if title_components else None
            logger.debug(
                "[WIDGET_CREATE] seq=%s stage=title_widget type=%s param=%s manager_seq=%s title_cls=%s title_id=%s checkbox_cls=%s checkbox_id=%s reset_cls=%s reset_id=%s",
                create_seq,
                creation_type.value,
                param_info.name,
                getattr(manager, "_pfm_seq", None),
                type(title_widget).__name__ if title_widget is not None else None,
                id(title_widget) if title_widget is not None else None,
                type(checkbox).__name__ if checkbox is not None else None,
                id(checkbox) if checkbox is not None else None,
                type(reset_btn).__name__ if reset_btn is not None else None,
                id(reset_btn) if reset_btn is not None else None,
            )
        except Exception:
            logger.debug("[WIDGET_CREATE] seq=%s stage=title_widget param=%s log_failed", create_seq, param_info.name)

    # Add label if needed (REGULAR only)
    if config.needs_label:
        # Compute dotted_path for provenance lookup
        dotted_path = f'{manager.field_id}.{param_info.name}' if manager.field_id else param_info.name

        import logging
        logger = logging.getLogger(__name__)
        scope_accent_color = getattr(manager, '_scope_accent_color', None)
        logger.debug(f"🔍 create_widget_parametric: Creating LabelWithHelp for param_name={param_info.name}, scope_accent_color={scope_accent_color}")
        label = LabelWithHelp(
            text=display_info['field_label'],
            param_name=param_info.name,
            param_description=display_info['description'],
            param_type=param_info.type,
            color_scheme=manager.config.color_scheme or PyQt6ColorScheme(),
            state=manager.state,
            dotted_path=dotted_path,
            scope_accent_color=scope_accent_color
        )
        try:
            parent_obj = label.parent()
            logger.debug(
                "[WIDGET_CREATE] seq=%s stage=label type=%s param=%s manager_seq=%s label_cls=%s id=%s parent_cls=%s",
                create_seq,
                creation_type.value,
                param_info.name,
                getattr(manager, "_pfm_seq", None),
                type(label).__name__,
                id(label),
                type(parent_obj).__name__ if parent_obj is not None else None,
            )
        except Exception:
            logger.debug("[WIDGET_CREATE] seq=%s stage=label param=%s log_failed", create_seq, param_info.name)
        # Check if using ResponsiveParameterRow
        if isinstance(container, ResponsiveParameterRow):
            container.set_label(label)
        else:
            layout.addWidget(label)
        # Store label for bold styling updates
        manager.labels[param_info.name] = label

        # Set initial label styling using ObjectState.signature_diff_fields (single source of truth)
        should_underline = dotted_path in manager.state.signature_diff_fields
        label.set_underline(should_underline)

    # Add main widget
    main_widget = ops['create_main_widget'](
        manager, param_info, display_info, field_ids, current_value, unwrapped_type,
        layout, CURRENT_LAYOUT, QWidget, GroupBoxWithHelp, PyQt6ColorScheme
    )
    try:
        parent_obj = main_widget.parent() if main_widget is not None else None
        logger.debug(
            "[WIDGET_CREATE] seq=%s stage=main_widget type=%s param=%s field_id=%s manager_seq=%s widget_cls=%s obj_name=%s id=%s parent_cls=%s",
            create_seq,
            creation_type.value,
            param_info.name,
            manager.config.field_id,
            getattr(manager, "_pfm_seq", None),
            type(main_widget).__name__ if main_widget is not None else None,
            main_widget.objectName() if main_widget is not None else None,
            id(main_widget) if main_widget is not None else None,
            type(parent_obj).__name__ if parent_obj is not None else None,
        )
    except Exception:
        logger.debug("[WIDGET_CREATE] seq=%s stage=main_widget param=%s log_failed", create_seq, param_info.name)

    # For nested widgets, add to container
    # For regular widgets, add to layout or use ResponsiveParameterRow
    if config.is_nested:
        if config.is_optional:
            # OPTIONAL_NESTED: set enabled state based on current_value
            main_widget.setEnabled(current_value is not None)
        layout.addWidget(main_widget)
    else:
        # Check if using ResponsiveParameterRow
        if isinstance(container, ResponsiveParameterRow):
            container.set_input(main_widget)
        else:
            layout.addWidget(main_widget, 1)

    # Add reset button if needed
    if config.needs_reset_button and not manager.read_only:
        if config.is_optional:
            # OPTIONAL_NESTED: reset button already in title widget, just connect it
            if title_components and title_components['reset_all_button']:
                nested_manager = manager.nested_managers.get(param_info.name)
                if nested_manager:
                    title_components['reset_all_button'].clicked.connect(lambda: nested_manager.reset_all_parameters())
        elif config.is_nested:
            # NESTED: "Reset All" button in GroupBox title
            from PyQt6.QtWidgets import QPushButton
            # Ensure help button stays immediately after title (left aligned)
            try:
                from PyQt6.QtWidgets import QHBoxLayout
                title_layout = getattr(container, "title_layout", None)
                title_label = getattr(container, "_title_label", None)
                help_button = getattr(container, "_help_button", None)
                if isinstance(title_layout, QHBoxLayout) and title_label and help_button:
                    title_idx = title_layout.indexOf(title_label)
                    help_idx = title_layout.indexOf(help_button)
                    if title_idx != -1 and help_idx != -1 and help_idx != title_idx + 1:
                        title_layout.removeWidget(help_button)
                        title_layout.insertWidget(title_idx + 1, help_button)
            except Exception:
                pass
            reset_all_button = QPushButton("Reset All")
            reset_all_button.setMaximumWidth(80)
            reset_all_button.setFixedHeight(CURRENT_LAYOUT.button_height)
            reset_all_button.setToolTip(f"Reset all parameters in {display_info['field_label']} to defaults")
            _apply_reset_button_style(reset_all_button, manager.color_scheme)
            try:
                logger.debug(
                    "[WIDGET_CREATE] seq=%s stage=reset_all type=%s param=%s manager_seq=%s reset_cls=%s id=%s",
                    create_seq,
                    creation_type.value,
                    param_info.name,
                    getattr(manager, "_pfm_seq", None),
                    type(reset_all_button).__name__,
                    id(reset_all_button),
                )
            except Exception:
                logger.debug("[WIDGET_CREATE] seq=%s stage=reset_all param=%s log_failed", create_seq, param_info.name)
            # Connect to nested manager's reset_all_parameters
            nested_manager = manager.nested_managers.get(param_info.name)
            if nested_manager:
                reset_all_button.clicked.connect(lambda: nested_manager.reset_all_parameters())
            container.addTitleWidget(reset_all_button)
        else:
            # REGULAR: reset button in layout (right-aligned via stretch)
            reset_button = _create_optimized_reset_button(
                manager.config.field_id,
                param_info.name,
                lambda: manager.reset_parameter(param_info.name)
            )
            try:
                logger.debug(
                    "[WIDGET_CREATE] seq=%s stage=reset_button type=%s param=%s manager_seq=%s reset_cls=%s id=%s",
                    create_seq,
                    creation_type.value,
                    param_info.name,
                    getattr(manager, "_pfm_seq", None),
                    type(reset_button).__name__,
                    id(reset_button),
                )
            except Exception:
                logger.debug("[WIDGET_CREATE] seq=%s stage=reset_button param=%s log_failed", create_seq, param_info.name)
            # Check if using ResponsiveParameterRow
            if isinstance(container, ResponsiveParameterRow):
                container.set_reset_button(reset_button)
            else:
                # Add stretch before reset button to push it to the right
                # This only applies to REGULAR widgets (label + widget + reset button rows)
                if not config.is_nested:
                    layout.addStretch()
                layout.addWidget(reset_button)
            manager.reset_buttons[param_info.name] = reset_button

    # Connect checkbox logic if needed (OPTIONAL_NESTED only)
    if config.needs_checkbox and title_components:
        nested_manager = manager.nested_managers.get(param_info.name)
        if nested_manager:
            ops['connect_checkbox_logic'](
                manager, param_info,
                title_components['checkbox'],
                main_widget,
                nested_manager,
                title_components['title_label'],
                title_components['help_btn'],
                unwrapped_type
            )

    # Store widget and connect signals
    if config.is_nested:
        # For nested, store the GroupBox/container
        manager.widgets[param_info.name] = container
        logger.debug(f"[CREATE_NESTED_DATACLASS] param_info.name={param_info.name}, stored container in manager.widgets")
    else:
        # For regular, store the main widget
        manager.widgets[param_info.name] = main_widget

        # Connect widget changes to dispatcher
        # NOTE: connect_change_signal calls callback(param_name, value)
        def on_widget_change(pname, value, mgr: ParameterFormManager = manager):
            converted_value = mgr._convert_widget_value(value, pname)
            event = FieldChangeEvent(pname, converted_value, mgr)
            # ATOMIC: If this manager's state has a parent (e.g., function in step),
            # wrap dispatch in atomic to coalesce with parent step update
            from objectstate import ObjectStateRegistry
            if mgr.state and mgr.state._parent_state is not None:
                with ObjectStateRegistry.atomic("edit func parameter"):
                    FieldChangeDispatcher.instance().dispatch(event)
            else:
                FieldChangeDispatcher.instance().dispatch(event)

        PyQt6WidgetEnhancer.connect_change_signal(main_widget, param_info.name, on_widget_change)

        if manager.read_only:
            WidgetService.make_readonly(main_widget, manager.config.color_scheme)

    return container


# ============================================================================
# VALIDATION
# ============================================================================

def _validate_widget_operations() -> None:
    """Validate that all widget creation types have required operations."""
    for creation_type, config in _WIDGET_CREATION_CONFIG.items():
        if config.create_container is None:
            raise RuntimeError(f"{creation_type.value}: create_container is required")
        if config.create_main_widget is None:
            raise RuntimeError(f"{creation_type.value}: create_main_widget is required")

    logger.debug(f"✅ Validated {len(_WIDGET_CREATION_CONFIG)} widget creation types")


# Run validation at module load time
_validate_widget_operations()
