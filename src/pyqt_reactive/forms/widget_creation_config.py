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

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import logging
import itertools

logger = logging.getLogger(__name__)
from typing import Any, Callable, ClassVar, Optional, TYPE_CHECKING, Type, Tuple
from metaclass_registry import AutoRegisterMeta

from .widget_creation_types import (
    ParameterFormManager, ParameterInfo, DisplayInfo, FieldIds,
    LayoutKind, OptionalTitleComponents, WidgetBuildContext, WidgetCreationConfig
)
from pyqt_reactive.services.field_change_dispatcher import FieldChangeDispatcher, FieldChangeEvent
from pyqt_reactive.services.widget_service import WidgetService
from pyqt_reactive.widgets.shared.responsive_layout_widgets import ResponsiveParameterRow
from pyqt_reactive.forms.layout_constants import CURRENT_LAYOUT

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QGroupBox, QLayout, QWidget
    from pyqt_reactive.widgets.no_scroll_spinbox import NoneAwareCheckBox
    from pyqt_reactive.widgets.shared.clickable_help_components import (
        GroupBoxWithHelp,
        InlineDataclassGroupBox,
        ProvenanceButton,
    )

_WIDGET_CREATE_SEQ = itertools.count(1)


def _root_manager(manager: ParameterFormManager) -> ParameterFormManager:
    """Return the root ParameterFormManager for a nested manager tree."""
    root = manager
    while root._parent_manager is not None:
        root = root._parent_manager
    return root


class WidgetCreationType(Enum):
    """
    Enum for widget creation strategies - mirrors MemoryType pattern.

    PyQt6 uses 3 parametric types: REGULAR, NESTED, and OPTIONAL_NESTED.
    """
    REGULAR = "regular"
    INLINE_DATACLASS = "inline_dataclass"
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


class ResetButtonStyler:
    """Canonical reset-button style authority."""

    @staticmethod
    def apply(button, color_scheme) -> None:
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


@dataclass(slots=True)
class EnabledTitleWidgetMoveRequest:
    """Request to move an enableable field widget into its group title."""

    nested_manager: ParameterFormManager
    parent_manager: ParameterFormManager | GroupBoxWithHelp
    nested_param_name: str
    enabled_field: str


@dataclass(slots=True)
class EnabledTitleWidgetMoveContext:
    """Resolved widgets and layouts for enabled-title relocation."""

    request: EnabledTitleWidgetMoveRequest
    container: GroupBoxWithHelp
    source_layout: QLayout
    enabled_widget: QWidget
    title_widget: QWidget
    checkbox_widget: NoneAwareCheckBox | None
    enabled_reset_button: QWidget | None


class EnabledTitleWidgetMoveAuthority:
    """Moves an enableable checkbox into the nested config title row."""

    def move(self, request: EnabledTitleWidgetMoveRequest) -> None:
        context = self.resolve_context(request)
        self.detach_source_row_widgets(context)
        self.wrap_checkbox_for_title(context)
        self.bind_title_toggle(context)
        self.prepare_reset_button(context)
        provenance_button = self.create_provenance_button(context)
        context.container.addEnableableWidgets(
            context.title_widget,
            context.enabled_reset_button,
            provenance_button,
        )
        self.remove_empty_source_row(context)
        logger.debug("🔍 _move_enabled_widget_to_title: COMPLETE")

    def resolve_context(
        self,
        request: EnabledTitleWidgetMoveRequest,
    ) -> EnabledTitleWidgetMoveContext:
        from pyqt_reactive.widgets.no_scroll_spinbox import NoneAwareCheckBox

        enabled_widget = self.enabled_widget(request)
        enabled_reset_button = request.nested_manager.reset_buttons.get(
            request.enabled_field
        )
        container = self.groupbox_container(request)
        source_layout = self.source_layout(enabled_widget)
        checkbox_widget = None
        if isinstance(enabled_widget, NoneAwareCheckBox):
            checkbox_widget = enabled_widget

        logger.debug(
            "🔍 _move_enabled_widget_to_title: resolved enabled_widget=%s reset=%s",
            enabled_widget,
            enabled_reset_button,
        )
        return EnabledTitleWidgetMoveContext(
            request=request,
            container=container,
            source_layout=source_layout,
            enabled_widget=enabled_widget,
            title_widget=enabled_widget,
            checkbox_widget=checkbox_widget,
            enabled_reset_button=enabled_reset_button,
        )

    def enabled_widget(self, request: EnabledTitleWidgetMoveRequest) -> QWidget:
        if request.enabled_field in request.nested_manager.widgets:
            return request.nested_manager.widgets[request.enabled_field]
        raise RuntimeError(
            f"Enableable field {request.enabled_field!r} is missing from "
            f"{request.nested_manager.field_id!r} widgets."
        )

    def groupbox_container(
        self,
        request: EnabledTitleWidgetMoveRequest,
    ) -> GroupBoxWithHelp:
        from pyqt_reactive.widgets.shared.clickable_help_components import (
            GroupBoxWithHelp,
        )

        if isinstance(request.parent_manager, ParameterFormManager):
            container = request.parent_manager.widgets.get(request.nested_param_name)
            if isinstance(container, GroupBoxWithHelp):
                return container
        if isinstance(request.parent_manager, GroupBoxWithHelp):
            return request.parent_manager
        raise RuntimeError(
            f"Enableable container {request.nested_param_name!r} is not a "
            "GroupBoxWithHelp."
        )

    def source_layout(self, enabled_widget: QWidget) -> QLayout:
        enabled_widget_parent = enabled_widget.parent()
        if enabled_widget_parent is None:
            raise RuntimeError("Enableable widget has no parent row.")

        enabled_widget_layout = enabled_widget_parent.layout()
        if enabled_widget_layout is None:
            raise RuntimeError("Enableable widget parent has no layout.")
        return enabled_widget_layout

    def detach_source_row_widgets(self, context: EnabledTitleWidgetMoveContext) -> None:
        enabled_label = context.request.nested_manager.labels.get(
            context.request.enabled_field
        )
        if enabled_label is not None:
            context.source_layout.removeWidget(enabled_label)
            enabled_label.hide()

        context.source_layout.removeWidget(context.enabled_widget)
        if context.enabled_reset_button is not None:
            context.source_layout.removeWidget(context.enabled_reset_button)

    def wrap_checkbox_for_title(self, context: EnabledTitleWidgetMoveContext) -> None:
        if context.checkbox_widget is None:
            return

        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QHBoxLayout, QStyle, QWidget

        parent_manager = context.request.parent_manager
        bg_color = parent_manager.color_scheme.to_hex(
            parent_manager.color_scheme.button_normal_bg
        )
        checkbox_container = QWidget()
        checkbox_container.setStyleSheet(f"background-color: {bg_color};")
        indicator_w = context.checkbox_widget.style().pixelMetric(
            QStyle.PixelMetric.PM_IndicatorWidth
        )
        indicator_h = context.checkbox_widget.style().pixelMetric(
            QStyle.PixelMetric.PM_IndicatorHeight
        )
        checkbox_container.setFixedSize(indicator_w, indicator_h)
        layout = QHBoxLayout(checkbox_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        context.checkbox_widget.setStyleSheet("padding: 0px; margin: 0px;")
        context.checkbox_widget.setFixedSize(indicator_w, indicator_h)
        context.checkbox_widget.setParent(checkbox_container)
        layout.addWidget(context.checkbox_widget)
        context.title_widget = checkbox_container

    def bind_title_toggle(self, context: EnabledTitleWidgetMoveContext) -> None:
        if context.checkbox_widget is None:
            return

        from PyQt6.QtCore import Qt

        title_label = context.container._title_label

        def on_title_click(event):
            context.checkbox_widget.toggle()

        title_label.mousePressEvent = on_title_click
        title_label.setCursor(Qt.CursorShape.PointingHandCursor)

    def prepare_reset_button(self, context: EnabledTitleWidgetMoveContext) -> None:
        if context.enabled_reset_button is None:
            return

        from pyqt_reactive.utils.styling_utils import update_reset_button_styling

        parent_manager = context.request.parent_manager
        ResetButtonStyler.apply(context.enabled_reset_button, parent_manager.color_scheme)
        context.enabled_reset_button.setMaximumWidth(60)
        context.enabled_reset_button.setFixedHeight(CURRENT_LAYOUT.button_height)
        update_reset_button_styling(
            context.enabled_reset_button,
            context.request.nested_manager.state,
            context.request.nested_manager.field_id,
            context.request.enabled_field,
        )

    def create_provenance_button(
        self,
        context: EnabledTitleWidgetMoveContext,
    ) -> ProvenanceButton:
        from pyqt_reactive.widgets.shared.clickable_help_components import (
            ProvenanceButton,
        )

        dotted_path = (
            f"{context.request.nested_manager.field_id}.{context.request.enabled_field}"
            if context.request.nested_manager.field_id
            else context.request.enabled_field
        )
        provenance_button = ProvenanceButton(
            text="^",
            color_scheme=context.request.parent_manager.color_scheme,
        )
        provenance_button.setMaximumWidth(25)
        provenance_button.setFixedHeight(CURRENT_LAYOUT.button_height)
        ResetButtonStyler.apply(
            provenance_button,
            context.request.parent_manager.color_scheme,
        )
        provenance_button.set_provenance_info(
            context.request.nested_manager.state,
            dotted_path,
        )
        provenance_button.setVisible(provenance_button._has_provenance())
        return provenance_button

    def remove_empty_source_row(
        self,
        context: EnabledTitleWidgetMoveContext,
    ) -> None:
        from PyQt6.QtWidgets import QWidget

        if context.source_layout.count() != 0:
            return

        row_parent = context.source_layout.parent()
        if isinstance(row_parent, QWidget):
            row_parent.setParent(None)


class WidgetCreationHandlers:
    """Nominal owner for widget creation operation handlers."""

    def _create_nested_form(ctx: WidgetBuildContext) -> QWidget:
        """
        Handler for creating nested form.

        NOTE: This creates the nested manager AND stores it in manager.nested_managers.
        The caller should NOT try to store it again.

        """
        import logging
        manager = ctx.manager
        param_info = ctx.param_info
        current_value = ctx.current_value
        unwrapped_type = ctx.unwrapped_type
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

                WidgetCreationHandlers._move_enabled_widget_to_title(nested_manager, manager, param_info.name, ENABLED_FIELD)

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
        logger.debug(f"🔍 _move_enabled_widget_to_title: enabled_field={enabled_field}, nested_param_name={nested_param_name}")
        logger.debug(f"🔍 _move_enabled_widget_to_title: nested_manager.widgets keys={list(nested_manager.widgets.keys())}")
        if isinstance(parent_manager, ParameterFormManager):
            logger.debug(f"🔍 _move_enabled_widget_to_title: parent_manager.widgets keys={list(parent_manager.widgets.keys())}")
        EnabledTitleWidgetMoveAuthority().move(
            EnabledTitleWidgetMoveRequest(
                nested_manager=nested_manager,
                parent_manager=parent_manager,
                nested_param_name=nested_param_name,
                enabled_field=enabled_field,
            )
        )

    def _create_optional_title_widget(ctx: WidgetBuildContext):
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

        manager = ctx.manager
        param_info = ctx.param_info
        display_info = ctx.display_info
        field_ids = ctx.field_ids
        current_value = ctx.current_value
        unwrapped_type = ctx.unwrapped_type

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
        scope_accent_color = manager._scope_accent_color

        # Help button (immediately to the right of the title)
        from pyqt_reactive.widgets.shared.clickable_help_components import HelpContext

        help_btn = HelpButton(
            help_context=HelpContext(
                help_target=unwrapped_type,
                color_scheme=manager.color_scheme,
                scope_accent_color=scope_accent_color,
                parent=title_widget,
            ),
            text="?",
        )
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
            ResetButtonStyler.apply(reset_all_button, manager.color_scheme)
            title_layout.addWidget(reset_all_button)

        return OptionalTitleComponents(
            title_widget=title_widget,
            checkbox=checkbox,
            title_label=title_label,
            help_btn=help_btn,
            reset_all_button=reset_all_button,
        )

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

    def _create_regular_container(ctx: WidgetBuildContext) -> QWidget:
        """Create container for REGULAR widget type."""
        from pyqt_reactive.widgets.shared.responsive_layout_widgets import (
            ResponsiveParameterRow, is_wrapping_enabled as is_row_wrapping_enabled
        )
    
        manager = ctx.manager
        parent = manager.parent()
    
        # Check if responsive wrapping is enabled
        if is_row_wrapping_enabled():
            # Use responsive row that wraps when narrow
            container = ResponsiveParameterRow(
                width_threshold=150, 
                parent=parent,
                layout_config=ctx.layout_config
            )
        else:
            # Use plain QWidget with QHBoxLayout (old non-wrapping style)
            from PyQt6.QtWidgets import QWidget as QtWidget
            container = QtWidget(parent)

        return container

    def _create_nested_container(ctx: WidgetBuildContext) -> GroupBoxWithHelp:
        """Create container for NESTED widget type."""
        from pyqt_reactive.widgets.shared.clickable_help_components import GroupBoxWithHelp as GBH
        from pyqt_reactive.theming.color_scheme import ColorScheme as PCS
        from pyqt_reactive.forms.form_init_service import FormBuildOrchestrator

        manager = ctx.manager
        param_info = ctx.param_info
        display_info = ctx.display_info
        unwrapped_type = ctx.unwrapped_type
        color_scheme = manager.config.color_scheme or PCS()
        # Get root manager for flash - nested managers share root's _flash_colors dict
        root_manager = _root_manager(manager)
        # Flash keys must identify the *section* via a canonical dotted path.
        # Example: "processing_config.path_planning_config" (not just "path_planning_config").
        flash_key = f"{manager.field_id}.{param_info.name}" if manager.field_id else param_info.name

        # CRITICAL: Use scope_accent_color from manager config (passed from parent window)
        # No need to walk parent chain - it's stored directly in the manager
        scope_accent_color = manager._scope_accent_color

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

    def _create_inline_dataclass_container(
        ctx: WidgetBuildContext,
    ) -> InlineDataclassGroupBox:
        """Create dataclass chrome for a registered inline dataclass editor."""
        from pyqt_reactive.widgets.shared.clickable_help_components import (
            InlineDataclassGroupBox,
        )
        from pyqt_reactive.theming.color_scheme import ColorScheme as PCS

        manager = ctx.manager
        param_info = ctx.param_info
        display_info = ctx.display_info
        unwrapped_type = ctx.unwrapped_type
        color_scheme = manager.config.color_scheme or PCS()
        root_manager = _root_manager(manager)
        flash_key = f"{manager.field_id}.{param_info.name}" if manager.field_id else param_info.name
        scope_accent_color = manager._scope_accent_color

        return InlineDataclassGroupBox(
            title=display_info['field_label'],
            help_target=unwrapped_type,
            color_scheme=color_scheme,
            scope_accent_color=scope_accent_color,
            flash_key=flash_key,
            flash_manager=root_manager,
        )

    def _create_inline_dataclass_widget(
        ctx: WidgetBuildContext,
    ) -> QWidget:
        """Create the registered inline editor for a structural dataclass value."""
        from .parameter_info_types import InlineDataclassWidgetInfo

        manager = ctx.manager
        param_info = ctx.param_info
        if not isinstance(param_info, InlineDataclassWidgetInfo):
            raise TypeError(
                "INLINE_DATACLASS creation requires InlineDataclassWidgetInfo; "
                f"got {type(param_info).__name__}."
            )
        widget_factory = param_info.widget_factory()
        return widget_factory(
            manager=manager,
            param_info=param_info,
            display_info=ctx.display_info,
            field_ids=ctx.field_ids,
            current_value=ctx.current_value,
            parent=manager,
        )

    def _create_optional_nested_container(ctx: WidgetBuildContext) -> QGroupBox:
        """Create container for OPTIONAL_NESTED widget type."""
        from PyQt6.QtWidgets import QGroupBox
        from PyQt6.QtGui import QPalette
        from pyqt_reactive.theming.color_scheme import ColorScheme as PCS
        import logging

        manager = ctx.manager
        display_info = ctx.display_info
        field_ids = ctx.field_ids
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

    def _setup_regular_layout(ctx: WidgetBuildContext) -> None:
        """Setup layout for REGULAR widget type.

        For REGULAR widgets, container is a QWidget with a layout already set.
        We need to configure the layout, not the container.
    
        If container is ResponsiveParameterRow, it manages its own layout so we skip setup.
        """
        # Skip layout setup for ResponsiveParameterRow - it manages its own layout
        container = ctx.container
        if isinstance(container, ResponsiveParameterRow):
            return
    
        layout = container.layout()
        # QLayout.__bool__ returns False even when the layout exists, so we do not
        # use a truthiness check here. For REGULAR rows we *require* that a layout
        # has already been set (create_widget_parametric installs a QHBoxLayout),
        # so if this ever ends up being None it's a programmer error and should
        # raise loudly.
        layout.setSpacing(ctx.layout_config.parameter_row_spacing)
        layout.setContentsMargins(*ctx.layout_config.parameter_row_margins)

    def _setup_optional_nested_layout(ctx: WidgetBuildContext) -> None:
        """Setup layout for OPTIONAL_NESTED widget type."""
        from PyQt6.QtWidgets import QVBoxLayout as QVL
        container = ctx.container
        container.setLayout(QVL())
        container.layout().setSpacing(0)
        container.layout().setContentsMargins(0, 0, 0, 0)


# ============================================================================
# UNIFIED WIDGET CREATION CONFIGURATION (typed, no eval strings)
# ============================================================================

_WIDGET_CREATION_CONFIG: dict[WidgetCreationType, WidgetCreationConfig] = {
    WidgetCreationType.REGULAR: WidgetCreationConfig(
        layout_type=LayoutKind.HORIZONTAL_ROW,
        is_nested=False,
        create_container=WidgetCreationHandlers._create_regular_container,
        setup_layout=WidgetCreationHandlers._setup_regular_layout,
        create_main_widget=lambda ctx: ctx.manager._widget_creator(
            ctx.param_info.name,
            ctx.param_info.type,
            ctx.current_value,
            ctx.field_ids['widget_id'],
            None,
        ),
        needs_label=True,
        needs_reset_button=True,
        needs_unwrap_type=False,
    ),

    WidgetCreationType.INLINE_DATACLASS: WidgetCreationConfig(
        layout_type=LayoutKind.GROUPBOX_WITH_HELP,
        is_nested=True,
        create_container=WidgetCreationHandlers._create_inline_dataclass_container,
        setup_layout=None,
        create_main_widget=WidgetCreationHandlers._create_inline_dataclass_widget,
        needs_label=False,
        needs_reset_button=False,
        needs_unwrap_type=True,
        is_optional=False,
    ),

    WidgetCreationType.NESTED: WidgetCreationConfig(
        layout_type=LayoutKind.GROUPBOX_WITH_HELP,
        is_nested=True,
        create_container=WidgetCreationHandlers._create_nested_container,
        setup_layout=None,
        create_main_widget=WidgetCreationHandlers._create_nested_form,
        needs_label=False,
        needs_reset_button=True,
        needs_unwrap_type=True,
        is_optional=False,
    ),

    WidgetCreationType.OPTIONAL_NESTED: WidgetCreationConfig(
        layout_type=LayoutKind.PRECONFIGURED_GROUPBOX,
        is_nested=True,
        create_container=WidgetCreationHandlers._create_optional_nested_container,
        setup_layout=WidgetCreationHandlers._setup_optional_nested_layout,
        create_main_widget=WidgetCreationHandlers._create_nested_form,
        needs_label=False,
        needs_reset_button=True,
        needs_unwrap_type=True,
        is_optional=True,
        needs_checkbox=True,
        create_title_widget=WidgetCreationHandlers._create_optional_title_widget,
        connect_checkbox_logic=WidgetCreationHandlers._connect_optional_checkbox_logic,
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


class LayoutStrategy(ABC, metaclass=AutoRegisterMeta):
    """Nominal layout creation strategy for widget containers."""

    __registry_key__ = "layout_kind"
    __skip_if_no_key__ = True
    layout_kind: ClassVar[LayoutKind | None] = None

    @classmethod
    def for_layout_kind(cls, layout_kind: LayoutKind) -> "LayoutStrategy":
        return cls.__registry__[layout_kind]()

    @abstractmethod
    def create_layout(self, container: QWidget) -> QLayout | None:
        pass


class HorizontalRowLayoutStrategy(LayoutStrategy):
    layout_kind = LayoutKind.HORIZONTAL_ROW

    def create_layout(self, container: QWidget) -> QLayout | None:
        from PyQt6.QtWidgets import QHBoxLayout
        if isinstance(container, ResponsiveParameterRow):
            return None
        return QHBoxLayout(container)


class VerticalBoxLayoutStrategy(LayoutStrategy):
    layout_kind = LayoutKind.VERTICAL_BOX

    def create_layout(self, container: QWidget) -> QLayout:
        from PyQt6.QtWidgets import QVBoxLayout
        return QVBoxLayout(container)


class PreconfiguredGroupBoxLayoutStrategy(LayoutStrategy):
    layout_kind = LayoutKind.PRECONFIGURED_GROUPBOX

    def create_layout(self, container: QWidget) -> None:
        return None


class GroupBoxWithHelpLayoutStrategy(LayoutStrategy):
    layout_kind = LayoutKind.GROUPBOX_WITH_HELP

    def create_layout(self, container: QWidget) -> QLayout | None:
        return container.layout()


# ============================================================================
# UNIFIED WIDGET CREATION FUNCTION
# ============================================================================

@dataclass
class WidgetCreationRuntime:
    """Mutable state for one widget-creation pipeline execution."""

    manager: ParameterFormManager
    param_info: ParameterInfo
    creation_type: WidgetCreationType
    config: WidgetCreationConfig
    ops: dict[str, Callable]
    ctx: WidgetBuildContext
    create_seq: int
    container: QWidget | None = None
    layout: QLayout | None = None
    title_components: OptionalTitleComponents | None = None
    main_widget: QWidget | None = None


class WidgetCreationPipeline:
    """Named stages for creating one parameter widget."""

    def __init__(self, manager: ParameterFormManager, param_info: ParameterInfo) -> None:
        from PyQt6.QtWidgets import QWidget
        from pyqt_reactive.widgets.shared.clickable_help_components import GroupBoxWithHelp
        from pyqt_reactive.theming.color_scheme import ColorScheme as PyQt6ColorScheme

        creation_type = WidgetCreationType[param_info.widget_creation_type]
        config = _WIDGET_CREATION_CONFIG[creation_type]
        display_info = WidgetService.get_parameter_display_info(
            param_info.name,
            param_info.type,
            manager=manager,
            description=param_info.description,
        )
        field_ids = manager.service.generate_field_ids_direct(manager.config.field_id, param_info.name)
        current_value = manager.parameters.get(param_info.name)
        unwrapped_type = None
        if config.needs_unwrap_type:
            unwrapped_type = _unwrap_optional_type(param_info.type)
        ctx = WidgetBuildContext(
            manager=manager,
            param_info=param_info,
            display_info=display_info,
            field_ids=field_ids,
            current_value=current_value,
            unwrapped_type=unwrapped_type,
            layout_config=CURRENT_LAYOUT,
            qwidget_type=QWidget,
            groupbox_with_help_type=GroupBoxWithHelp,
            color_scheme_type=PyQt6ColorScheme,
        )
        self.runtime = WidgetCreationRuntime(
            manager=manager,
            param_info=param_info,
            creation_type=creation_type,
            config=config,
            ops=_get_widget_operations(creation_type),
            ctx=ctx,
            create_seq=next(_WIDGET_CREATE_SEQ),
        )
        logger.debug(
            "create_widget_parametric: config type=%s is_nested=%s is_optional=%s",
            type(config).__name__,
            config.is_nested,
            config.is_optional,
        )

    def run(self) -> QWidget:
        """Run the widget creation stages."""
        self.create_container()
        self.configure_nested_container()
        self.setup_layout()
        self.add_optional_title()
        self.add_regular_label()
        self.create_main_widget()
        self.place_main_widget()
        self.add_reset_controls()
        self.connect_optional_checkbox()
        self.store_and_connect_widget()
        return self.runtime.container

    def create_container(self) -> None:
        rt = self.runtime
        rt.container = rt.ops['create_container'](rt.ctx)
        rt.ctx = rt.ctx.with_container(rt.container)
        self._log_widget("container", rt.container)

    def configure_nested_container(self) -> None:
        from pyqt_reactive.widgets.shared.clickable_help_components import GroupBoxWithHelp

        rt = self.runtime
        if not (rt.config.is_nested and isinstance(rt.container, GroupBoxWithHelp)):
            return

        _root_manager(rt.manager).register_flash_groupbox(rt.container._flash_key, rt.container)
        scope_color_scheme = rt.manager._scope_color_scheme
        if scope_color_scheme is None:
            scope_color_scheme = _root_manager(rt.manager)._scope_color_scheme
        if scope_color_scheme:
            rt.container.set_scope_color_scheme(scope_color_scheme)

    def setup_layout(self) -> None:
        rt = self.runtime
        rt.layout = LayoutStrategy.for_layout_kind(rt.config.layout_type).create_layout(rt.container)
        rt.ctx = rt.ctx.with_layout(rt.layout)
        if rt.ops.get('setup_layout'):
            rt.ops['setup_layout'](rt.ctx)
            if rt.config.layout_type is LayoutKind.PRECONFIGURED_GROUPBOX:
                rt.layout = rt.container.layout()
                rt.ctx = rt.ctx.with_layout(rt.layout)

    def add_optional_title(self) -> None:
        rt = self.runtime
        if not rt.config.is_optional:
            return
        rt.title_components = rt.ops['create_title_widget'](rt.ctx)
        rt.layout.addWidget(rt.title_components.title_widget)
        reset_button_class = None
        reset_button_id = None
        if rt.title_components.reset_all_button is not None:
            reset_button_class = type(rt.title_components.reset_all_button).__name__
            reset_button_id = id(rt.title_components.reset_all_button)
        logger.debug(
            "[WIDGET_CREATE] seq=%s stage=title_widget type=%s param=%s manager_seq=%s title_cls=%s title_id=%s checkbox_cls=%s checkbox_id=%s reset_cls=%s reset_id=%s",
            rt.create_seq,
            rt.creation_type.value,
            rt.param_info.name,
            rt.manager._pfm_seq,
            type(rt.title_components.title_widget).__name__,
            id(rt.title_components.title_widget),
            type(rt.title_components.checkbox).__name__,
            id(rt.title_components.checkbox),
            reset_button_class,
            reset_button_id,
        )

    def add_regular_label(self) -> None:
        from pyqt_reactive.widgets.shared.clickable_help_components import HelpContext, LabelWithHelp
        from pyqt_reactive.theming.color_scheme import ColorScheme as PyQt6ColorScheme

        rt = self.runtime
        if not rt.config.needs_label:
            return

        dotted_path = f'{rt.manager.field_id}.{rt.param_info.name}' if rt.manager.field_id else rt.param_info.name
        label = LabelWithHelp(
            text=rt.ctx.display_info['field_label'],
            help_context=HelpContext(
                help_target=rt.manager.function_target,
                param_name=rt.param_info.name,
                param_description=rt.ctx.display_info['description'],
                param_type=rt.param_info.type,
                color_scheme=rt.manager.config.color_scheme or PyQt6ColorScheme(),
                scope_accent_color=rt.manager._scope_accent_color,
            ),
            state=rt.manager.state,
            dotted_path=dotted_path,
        )
        self._log_widget("label", label)
        if isinstance(rt.container, ResponsiveParameterRow):
            rt.container.set_label(label)
        else:
            rt.layout.addWidget(label)
        rt.manager.labels[rt.param_info.name] = label
        label.set_underline(dotted_path in rt.manager.state.signature_diff_fields)

    def create_main_widget(self) -> None:
        rt = self.runtime
        rt.main_widget = rt.ops['create_main_widget'](rt.ctx)
        self._log_widget("main_widget", rt.main_widget)

    def place_main_widget(self) -> None:
        rt = self.runtime
        if rt.config.is_nested:
            if rt.config.is_optional:
                rt.main_widget.setEnabled(rt.ctx.current_value is not None)
            rt.layout.addWidget(rt.main_widget)
        elif isinstance(rt.container, ResponsiveParameterRow):
            rt.container.set_input(rt.main_widget)
        else:
            rt.layout.addWidget(rt.main_widget, 1)

    def add_reset_controls(self) -> None:
        rt = self.runtime
        if not (rt.config.needs_reset_button and not rt.manager.read_only):
            return
        if rt.config.is_optional:
            self._connect_optional_reset_button()
        elif rt.config.is_nested:
            self._add_nested_reset_button()
        else:
            self._add_regular_reset_button()

    def _connect_optional_reset_button(self) -> None:
        rt = self.runtime
        if rt.title_components is None or rt.title_components.reset_all_button is None:
            return
        nested_manager = rt.manager.nested_managers.get(rt.param_info.name)
        if nested_manager:
            rt.title_components.reset_all_button.clicked.connect(lambda: nested_manager.reset_all_parameters())

    def _add_nested_reset_button(self) -> None:
        from PyQt6.QtWidgets import QHBoxLayout, QPushButton

        rt = self.runtime
        title_layout = rt.container.title_layout
        title_label = rt.container._title_label
        help_button = rt.container._help_button
        if isinstance(title_layout, QHBoxLayout) and title_label and help_button:
            title_idx = title_layout.indexOf(title_label)
            help_idx = title_layout.indexOf(help_button)
            if title_idx != -1 and help_idx != -1 and help_idx != title_idx + 1:
                title_layout.removeWidget(help_button)
                title_layout.insertWidget(title_idx + 1, help_button)

        reset_all_button = QPushButton("Reset All")
        reset_all_button.setMaximumWidth(80)
        reset_all_button.setFixedHeight(CURRENT_LAYOUT.button_height)
        reset_all_button.setToolTip(f"Reset all parameters in {rt.ctx.display_info['field_label']} to defaults")
        ResetButtonStyler.apply(reset_all_button, rt.manager.color_scheme)
        self._log_widget("reset_all", reset_all_button)
        nested_manager = rt.manager.nested_managers.get(rt.param_info.name)
        if nested_manager:
            reset_all_button.clicked.connect(lambda: nested_manager.reset_all_parameters())
        rt.container.addTitleWidget(reset_all_button)

    def _add_regular_reset_button(self) -> None:
        rt = self.runtime
        reset_button = _create_optimized_reset_button(
            rt.manager.config.field_id,
            rt.param_info.name,
            lambda: rt.manager.reset_parameter(rt.param_info.name),
        )
        self._log_widget("reset_button", reset_button)
        if isinstance(rt.container, ResponsiveParameterRow):
            rt.container.set_reset_button(reset_button)
        else:
            rt.layout.addStretch()
            rt.layout.addWidget(reset_button)
        rt.manager.reset_buttons[rt.param_info.name] = reset_button

    def connect_optional_checkbox(self) -> None:
        rt = self.runtime
        if not (rt.config.needs_checkbox and rt.title_components):
            return
        nested_manager = rt.manager.nested_managers.get(rt.param_info.name)
        if nested_manager:
            rt.ops['connect_checkbox_logic'](
                rt.manager,
                rt.param_info,
                rt.title_components.checkbox,
                rt.main_widget,
                nested_manager,
                rt.title_components.title_label,
                rt.title_components.help_btn,
                rt.ctx.unwrapped_type,
            )

    def store_and_connect_widget(self) -> None:
        from pyqt_reactive.forms.widget_strategies import PyQt6WidgetEnhancer

        rt = self.runtime
        if rt.config.is_nested:
            if rt.creation_type is WidgetCreationType.INLINE_DATACLASS:
                rt.container.set_value_widget(rt.main_widget)
                rt.manager.widgets[rt.param_info.name] = rt.container
                PyQt6WidgetEnhancer.connect_change_signal(
                    rt.container,
                    rt.param_info.name,
                    self.on_widget_change,
                )
                logger.debug(
                    "[CREATE_INLINE_DATACLASS] param_info.name=%s, stored inline container in manager.widgets",
                    rt.param_info.name,
                )
            else:
                rt.manager.widgets[rt.param_info.name] = rt.container
                logger.debug("[CREATE_NESTED_DATACLASS] param_info.name=%s, stored container in manager.widgets", rt.param_info.name)
            return

        rt.manager.widgets[rt.param_info.name] = rt.main_widget
        PyQt6WidgetEnhancer.connect_change_signal(rt.main_widget, rt.param_info.name, self.on_widget_change)
        if rt.manager.read_only:
            WidgetService.make_readonly(rt.main_widget, rt.manager.config.color_scheme)

    def on_widget_change(self, pname, value) -> None:
        from objectstate import ObjectStateRegistry

        manager = self.runtime.manager
        converted_value = manager._convert_widget_value(value, pname)
        event = FieldChangeEvent(pname, converted_value, manager)
        if manager.state and manager.state._parent_state is not None:
            with ObjectStateRegistry.atomic("edit func parameter"):
                FieldChangeDispatcher.instance().dispatch(event)
        else:
            FieldChangeDispatcher.instance().dispatch(event)

    def _log_widget(self, stage: str, widget: QWidget | None) -> None:
        rt = self.runtime
        try:
            parent_obj = None
            widget_class = None
            widget_name = None
            widget_id = None
            parent_class = None
            if widget is not None:
                parent_obj = widget.parent()
                widget_class = type(widget).__name__
                widget_name = widget.objectName()
                widget_id = id(widget)
            if parent_obj is not None:
                parent_class = type(parent_obj).__name__
            logger.debug(
                "[WIDGET_CREATE] seq=%s stage=%s type=%s param=%s field_id=%s manager_seq=%s widget_cls=%s obj_name=%s id=%s parent_cls=%s",
                rt.create_seq,
                stage,
                rt.creation_type.value,
                rt.param_info.name,
                rt.manager.config.field_id,
                rt.manager._pfm_seq,
                widget_class,
                widget_name,
                widget_id,
                parent_class,
            )
        except Exception:
            logger.debug("[WIDGET_CREATE] seq=%s stage=%s param=%s log_failed", rt.create_seq, stage, rt.param_info.name)


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
