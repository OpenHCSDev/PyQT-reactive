"""Qt field creation and lifecycle behavior follows ParameterInfo inheritance."""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import nullcontext
from dataclasses import dataclass
import logging
import itertools
from typing import Callable, ClassVar, TYPE_CHECKING
from metaclass_registry import AutoRegisterMeta
from python_introspect import resolve_optional

from .widget_creation_types import (
    ParameterFormManager, ParameterInfo,
    OptionalTitleComponents, WidgetBuildContext
)
from pyqt_reactive.services.field_change_dispatcher import FieldChangeDispatcher, FieldChangeEvent
from pyqt_reactive.services.widget_service import WidgetService
from pyqt_reactive.widgets.shared.responsive_layout_widgets import ResponsiveParameterRow
from formbridge.forms.layout_constants import CURRENT_LAYOUT
from formbridge.forms.parameter_info_types import DirectDataclassInfo, InlineDataclassWidgetInfo, OptionalDataclassInfo

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QGroupBox, QLayout, QWidget
    from pyqt_reactive.widgets.no_scroll_spinbox import NoneAwareCheckBox
    from pyqt_reactive.widgets.shared.clickable_help_components import (
        GroupBoxWithHelp,
        InlineDataclassGroupBox,
        ProvenanceButton,
    )

_WIDGET_CREATE_SEQ = itertools.count(1)


# ============================================================================
# WIDGET CREATION HANDLERS - Special-case logic (like framework handlers)
# ============================================================================

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
    source_row: ResponsiveParameterRow | None
    enabled_widget: QWidget
    title_widget: QWidget
    checkbox_widget: NoneAwareCheckBox | None
    enabled_reset_button: QWidget | None
    provenance_button: QWidget | None = None


class EnabledTitleWidgetMoveAuthority:
    """Moves an enableable checkbox into the nested config title row."""

    def move(self, request: EnabledTitleWidgetMoveRequest) -> None:
        context = self.resolve_context(request)
        self.detach_source_row_widgets(context)
        self.wrap_checkbox_for_title(context)
        self.bind_title_toggle(context)
        self.prepare_reset_button(context)
        provenance_button = self.create_provenance_button(context)
        context.provenance_button = provenance_button
        context.container.addEnableableWidgets(
            context.title_widget,
            context.enabled_reset_button,
            provenance_button,
        )
        self.register_title_flash_target(context)
        self.remove_empty_source_row(context)
        context.request.nested_manager._enabled_field_styling_service.invalidate_widget_cache(
            context.request.nested_manager
        )
        if isinstance(context.request.parent_manager, ParameterFormManager):
            context.request.parent_manager._enabled_field_styling_service.invalidate_widget_cache(
                context.request.parent_manager
            )
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
        source_row = self.responsive_source_row(enabled_widget)
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
            source_row=source_row,
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

    @staticmethod
    def responsive_source_row(
        enabled_widget: QWidget,
    ) -> ResponsiveParameterRow | None:
        """Return the responsive row that currently owns the field widget."""

        ancestor = enabled_widget.parentWidget()
        while ancestor is not None:
            if isinstance(ancestor, ResponsiveParameterRow):
                return ancestor
            ancestor = ancestor.parentWidget()
        return None

    def detach_source_row_widgets(self, context: EnabledTitleWidgetMoveContext) -> None:
        enabled_label = context.request.nested_manager.labels.get(
            context.request.enabled_field
        )
        source_widgets = tuple(
            widget
            for widget in (
                enabled_label,
                context.enabled_widget,
                context.enabled_reset_button,
            )
            if widget is not None
        )
        if context.source_row is not None:
            context.source_row.release_widgets(*source_widgets)
        else:
            for widget in source_widgets:
                context.source_layout.removeWidget(widget)

        if enabled_label is not None:
            enabled_label.hide()
            enabled_label.setParent(None)

    def wrap_checkbox_for_title(self, context: EnabledTitleWidgetMoveContext) -> None:
        if context.checkbox_widget is None:
            return

        context.title_widget = self.wrap_checkbox_widget_for_title(
            context.checkbox_widget,
            context.request.parent_manager.color_scheme,
        )

    @staticmethod
    def wrap_checkbox_widget_for_title(
        checkbox_widget: NoneAwareCheckBox,
        color_scheme,
    ) -> QWidget:
        """Return the standard compact title-row container for an enableable checkbox."""

        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QHBoxLayout, QStyle, QWidget

        bg_color = color_scheme.to_hex(color_scheme.button_normal_bg)
        checkbox_container = QWidget()
        checkbox_container.setStyleSheet(f"background-color: {bg_color};")
        indicator_w = checkbox_widget.style().pixelMetric(
            QStyle.PixelMetric.PM_IndicatorWidth
        )
        indicator_h = checkbox_widget.style().pixelMetric(
            QStyle.PixelMetric.PM_IndicatorHeight
        )
        checkbox_container.setFixedSize(indicator_w, indicator_h)
        layout = QHBoxLayout(checkbox_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        checkbox_widget.setStyleSheet("padding: 0px; margin: 0px;")
        checkbox_widget.setFixedSize(indicator_w, indicator_h)
        checkbox_widget.setParent(checkbox_container)
        layout.addWidget(checkbox_widget)
        return checkbox_container

    def bind_title_toggle(self, context: EnabledTitleWidgetMoveContext) -> None:
        if context.checkbox_widget is None:
            return

        self.bind_title_label_to_checkbox(context.container, context.checkbox_widget)

    @staticmethod
    def bind_title_label_to_checkbox(
        container: GroupBoxWithHelp,
        checkbox_widget: NoneAwareCheckBox,
    ) -> None:
        """Make an enableable group title click toggle the owning checkbox."""

        from PyQt6.QtCore import Qt

        title_label = container._title_label

        def on_title_click(event):
            checkbox_widget.toggle()

        title_label.mousePressEvent = on_title_click
        title_label.setCursor(Qt.CursorShape.PointingHandCursor)

    def prepare_reset_button(self, context: EnabledTitleWidgetMoveContext) -> None:
        if context.enabled_reset_button is None:
            return

        from formbridge.utils.styling_utils import update_reset_button_styling

        self.prepare_title_reset_button(
            context.enabled_reset_button,
            context.request.parent_manager.color_scheme,
        )
        update_reset_button_styling(
            context.enabled_reset_button,
            context.request.nested_manager.state,
            context.request.nested_manager.field_id,
            context.request.enabled_field,
        )

    @staticmethod
    def prepare_title_reset_button(reset_button: QWidget, color_scheme) -> None:
        """Apply the standard enableable title reset-button styling."""

        ResetButtonStyler.apply(reset_button, color_scheme)
        reset_button.setMaximumWidth(60)
        reset_button.setFixedHeight(CURRENT_LAYOUT.button_height)

    def register_title_flash_target(
        self,
        context: EnabledTitleWidgetMoveContext,
    ) -> None:
        """Register title-row field chrome as this field's structural flash target."""

        context.request.nested_manager.register_field_flash_target(
            context.request.enabled_field,
            self.title_field_flash_target(
                container=context.container,
                title_widget=context.title_widget,
                checkbox_widget=context.checkbox_widget,
                reset_button=context.enabled_reset_button,
                provenance_button=context.provenance_button,
            ),
        )

    @staticmethod
    def title_field_flash_target(
        *,
        container: GroupBoxWithHelp,
        title_widget: QWidget,
        checkbox_widget: QWidget | None = None,
        reset_button: QWidget | None = None,
        provenance_button: QWidget | None = None,
    ):
        """Build the standard structural target for enableable title chrome."""

        from PyQt6.QtWidgets import QWidget
        from pyqt_reactive.widgets.structural_table import (
            StructuralMaskedContainerTarget,
            StructuralWidgetTarget,
            StructuralWidgetSetTarget,
        )

        chrome_widgets = tuple(
            widget
            for widget in (
                container._title_label,
                checkbox_widget or title_widget,
                reset_button,
                provenance_button,
            )
            if isinstance(widget, QWidget)
        )
        return StructuralMaskedContainerTarget(
            container=container,
            masked_target=StructuralWidgetSetTarget(chrome_widgets),
            scroll_target=StructuralWidgetTarget(container._title_label),
        )

    def create_provenance_button(
        self,
        context: EnabledTitleWidgetMoveContext,
    ) -> ProvenanceButton:
        dotted_path = context.request.nested_manager._object_state_path_for_field(
            context.request.enabled_field
        ).value
        return self.create_title_provenance_button(
            state=context.request.nested_manager.state,
            dotted_path=dotted_path,
            color_scheme=context.request.parent_manager.color_scheme,
        )

    @staticmethod
    def create_title_provenance_button(
        *,
        state,
        dotted_path: str,
        color_scheme,
    ) -> ProvenanceButton:
        """Create the standard provenance button for an enableable title field."""

        from pyqt_reactive.widgets.shared.clickable_help_components import (
            ProvenanceButton,
        )

        provenance_button = ProvenanceButton(
            text="^",
            color_scheme=color_scheme,
        )
        provenance_button.setMaximumWidth(25)
        provenance_button.setFixedHeight(CURRENT_LAYOUT.button_height)
        ResetButtonStyler.apply(
            provenance_button,
            color_scheme,
        )
        provenance_button.set_provenance_info(state, dotted_path)
        provenance_button.setVisible(provenance_button._has_provenance())
        return provenance_button

    def remove_empty_source_row(
        self,
        context: EnabledTitleWidgetMoveContext,
    ) -> None:
        from PyQt6.QtWidgets import QWidget

        if context.source_row is not None:
            if not context.source_row.is_empty():
                return
            context.source_row.hide()
            context.source_row.setParent(None)
            context.source_row.deleteLater()
            return

        if context.source_layout.count() != 0:
            return

        row_parent = context.source_layout.parent()
        if isinstance(row_parent, QWidget):
            row_parent.setParent(None)


class WidgetCreationConfig(ABC, metaclass=AutoRegisterMeta):
    """The admitted declaration's MRO selects all Qt creation behavior."""

    __registry_key__ = "parameter_type"
    __skip_if_no_key__ = True
    parameter_type: ClassVar[type[ParameterInfo] | None] = None

    @classmethod
    def for_parameter(cls, info: ParameterInfo) -> WidgetCreationConfig:
        for declaration in type(info).__mro__:
            implementation = cls.__registry__.get(declaration)
            if implementation is not None:
                return implementation()
        raise LookupError(f"No Qt form for {type(info).__qualname__}")

    @abstractmethod
    def create_container(self, ctx: WidgetBuildContext) -> QWidget:
        """Create this frontend's container."""
        raise NotImplementedError

    @abstractmethod
    def create_main_widget(self, ctx: WidgetBuildContext) -> QWidget:
        """Create this frontend's editor."""
        raise NotImplementedError

    def reset_callback(self, runtime: WidgetCreationRuntime) -> Callable[[], None]:
        return lambda: runtime.ctx.manager.reset_parameter(runtime.ctx.param_info.name)

    def store_widget(self, runtime: WidgetCreationRuntime, on_change: Callable) -> None:
        from pyqt_reactive.forms.widget_strategies import PyQt6WidgetEnhancer
        widget = runtime.main_widget
        runtime.ctx.manager.widgets[runtime.ctx.param_info.name] = widget
        PyQt6WidgetEnhancer.connect_change_signal(widget, runtime.ctx.param_info.name, on_change)
        if runtime.ctx.manager.read_only:
            WidgetService.make_readonly(widget, runtime.ctx.manager.config.color_scheme)

    def unwrapped_type(self, info: ParameterInfo) -> type | None:
        return None

    def content_update(self, rt: WidgetCreationRuntime):
        return nullcontext()

    def configure_container(self, rt: WidgetCreationRuntime) -> None:
        pass

    @abstractmethod
    def create_layout(self, ctx: WidgetBuildContext) -> QLayout | None:
        """Create the layout required by this owner's container."""
        raise NotImplementedError

    def add_title(self, rt: WidgetCreationRuntime) -> None:
        """Containers with their own title need no additional title widget."""

    def place_widget(self, rt: WidgetCreationRuntime) -> None:
        rt.ctx.layout.addWidget(rt.main_widget)

    def add_reset_controls(self, rt: WidgetCreationRuntime) -> None:
        if not rt.ctx.manager.read_only:
            self.add_reset_button(rt)

    @abstractmethod
    def add_reset_button(self, rt: WidgetCreationRuntime) -> None:
        raise NotImplementedError

    def connect_structure(self, rt: WidgetCreationRuntime) -> None:
        """Ordinary and direct dataclass fields have no presence checkbox."""


class RegularWidgetCreation(WidgetCreationConfig):
    parameter_type = ParameterInfo

    @staticmethod
    def create_container(ctx: WidgetBuildContext) -> QWidget:
        """Create container for REGULAR widget type."""
        from pyqt_reactive.widgets.shared.responsive_layout_widgets import (
            ResponsiveParameterRow,
        )

        return ResponsiveParameterRow(
            parent=ctx.manager.parent(),
            layout_config=ctx.layout_config,
        )

    @staticmethod
    def create_main_widget(ctx: WidgetBuildContext) -> QWidget:
        return ctx.manager._widget_creator(ctx.param_info.name, ctx.param_info.type,
                                          ctx.current_value, ctx.field_ids['widget_id'], None)

    def content_update(self, rt: WidgetCreationRuntime):
        return rt.ctx.container.layout_update()

    def create_layout(self, ctx: WidgetBuildContext) -> None:
        # ResponsiveParameterRow owns and batches its internal layout.
        return None

    def add_title(self, rt: WidgetCreationRuntime) -> None:
        from pyqt_reactive.widgets.shared.clickable_help_components import HelpContext, LabelWithHelp
        from pyqt_reactive.theming.color_scheme import ColorScheme as PyQt6ColorScheme

        dotted_path = rt.ctx.manager._object_state_path_for_field(rt.ctx.param_info.name).value
        label = LabelWithHelp(
            text=rt.ctx.display_info['field_label'],
            help_context=HelpContext(
                help_target=rt.ctx.manager.function_target,
                param_name=rt.ctx.param_info.name,
                param_description=rt.ctx.display_info['description'],
                param_type=rt.ctx.param_info.type,
                color_scheme=rt.ctx.manager.config.color_scheme or PyQt6ColorScheme(),
                scope_accent_color=rt.ctx.manager._scope_accent_color,
            ),
            state=rt.ctx.manager.state,
            dotted_path=dotted_path,
        )
        rt.log_widget("label", label)
        rt.ctx.container.set_label(label)
        rt.ctx.manager.labels[rt.ctx.param_info.name] = label
        label.set_underline(dotted_path in rt.ctx.manager.state.signature_diff_fields)

    def place_widget(self, rt: WidgetCreationRuntime) -> None:
        rt.ctx.container.set_input(rt.main_widget)

    def add_reset_button(self, rt: WidgetCreationRuntime) -> None:
        reset_button = _create_optimized_reset_button(
            rt.ctx.manager.config.field_id,
            rt.ctx.param_info.name,
            self.reset_callback(rt),
        )
        rt.log_widget("reset_button", reset_button)
        rt.ctx.container.set_reset_button(reset_button)
        rt.ctx.manager.reset_buttons[rt.ctx.param_info.name] = reset_button


class NestedWidgetCreation(WidgetCreationConfig):
    parameter_type = DirectDataclassInfo

    @staticmethod
    def create_container(ctx: WidgetBuildContext) -> GroupBoxWithHelp:
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
        root_manager = manager.form_tree.root()
        # Flash keys must identify the *section* via a canonical dotted path.
        # Example: "processing_config.path_planning_config" (not just "path_planning_config").
        flash_key = manager._object_state_path_for_field(param_info.name).value

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

    @staticmethod
    def create_main_widget(ctx: WidgetBuildContext) -> QWidget:
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
        from python_introspect import Enableable, is_enableable
        if is_enableable(unwrapped_type):
            enabled_field = Enableable.require_parameter_name()
            logger.debug(f"🔍 _create_nested_form: Registering callback to move enabled widget for {param_info.name}")
            logger.debug(f"🔍 _create_nested_form: nested_manager._on_build_complete_callbacks count BEFORE: {len(nested_manager._on_build_complete_callbacks)}")

            # Register callback to move enabled widget AND apply initial styling
            def on_build_complete():
                import logging
                log = logging.getLogger(__name__)
                log.debug(f"[BUILD_COMPLETE] FIRED for {nested_manager.field_id}, widget_count={len(nested_manager.widgets)}, widgets={list(nested_manager.widgets.keys())}")

                EnabledTitleWidgetMoveAuthority().move(EnabledTitleWidgetMoveRequest(
                    nested_manager=nested_manager, parent_manager=manager,
                    nested_param_name=param_info.name, enabled_field=enabled_field,
                ))

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

    def unwrapped_type(self, info: ParameterInfo) -> type:
        return resolve_optional(info.type)

    def configure_container(self, rt: WidgetCreationRuntime) -> None:
        root_manager = rt.ctx.manager.form_tree.root()
        root_manager.register_flash_groupbox(rt.ctx.container._flash_key, rt.ctx.container)
        scope_color_scheme = rt.ctx.manager._scope_color_scheme
        if scope_color_scheme is None:
            scope_color_scheme = root_manager._scope_color_scheme
        if scope_color_scheme:
            rt.ctx.container.set_scope_color_scheme(scope_color_scheme)

    def create_layout(self, ctx: WidgetBuildContext) -> QLayout:
        return ctx.container.layout()

    def reset_callback(self, runtime: WidgetCreationRuntime) -> Callable[[], None]:
        nested_manager = runtime.ctx.manager.nested_managers.get(runtime.ctx.param_info.name)
        if nested_manager is None:
            raise RuntimeError(f"Nested dataclass {runtime.ctx.param_info.name!r} has no nested manager.")
        return nested_manager.reset_all_parameters

    def add_reset_button(self, rt: WidgetCreationRuntime) -> None:
        from PyQt6.QtWidgets import QPushButton

        reset_all_button = QPushButton("Reset All")
        reset_all_button.setMaximumWidth(80)
        reset_all_button.setFixedHeight(CURRENT_LAYOUT.button_height)
        reset_all_button.setToolTip(f"Reset all parameters in {rt.ctx.display_info['field_label']} to defaults")
        ResetButtonStyler.apply(reset_all_button, rt.ctx.manager.color_scheme)
        rt.log_widget("reset_all", reset_all_button)
        reset_all = self.reset_callback(rt)
        reset_all_button.clicked.connect(lambda: reset_all())
        rt.ctx.container.addResetAllTitleWidget(reset_all_button)

    def store_widget(self, runtime: WidgetCreationRuntime, on_change: Callable) -> None:
        runtime.ctx.manager.widgets[runtime.ctx.param_info.name] = runtime.ctx.container


class InlineWidgetCreation(NestedWidgetCreation):
    parameter_type = InlineDataclassWidgetInfo

    @staticmethod
    def create_container(
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
        root_manager = manager.form_tree.root()
        flash_key = manager._object_state_path_for_field(param_info.name).value
        scope_accent_color = manager._scope_accent_color

        return InlineDataclassGroupBox(
            title=display_info['field_label'],
            help_target=unwrapped_type,
            color_scheme=color_scheme,
            scope_accent_color=scope_accent_color,
            flash_key=flash_key,
            flash_manager=root_manager,
        )

    @staticmethod
    def create_main_widget(
        ctx: WidgetBuildContext,
    ) -> QWidget:
        """Create the registered inline editor for a structural dataclass value."""
        manager = ctx.manager
        param_info = ctx.param_info
        widget_factory = param_info.widget_factory()
        return widget_factory(
            manager=manager,
            param_info=param_info,
            display_info=ctx.display_info,
            field_ids=ctx.field_ids,
            current_value=ctx.current_value,
            parent=manager,
        )

    def reset_callback(self, runtime: WidgetCreationRuntime) -> Callable[[], None]:
        return runtime.ctx.container.reset_inline_dataclass_fields

    def store_widget(self, runtime: WidgetCreationRuntime, on_change: Callable) -> None:
        from pyqt_reactive.forms.widget_strategies import PyQt6WidgetEnhancer
        runtime.ctx.container.set_value_widget(runtime.main_widget)
        super().store_widget(runtime, on_change)
        PyQt6WidgetEnhancer.connect_change_signal(runtime.ctx.container, runtime.ctx.param_info.name, on_change)


class OptionalNestedWidgetCreation(NestedWidgetCreation):
    parameter_type = OptionalDataclassInfo

    @staticmethod
    def create_container(ctx: WidgetBuildContext) -> QGroupBox:
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

    def configure_container(self, rt: WidgetCreationRuntime) -> None:
        # QGroupBox presence titles do not use GroupBoxWithHelp flash chrome.
        pass

    def create_layout(self, ctx: WidgetBuildContext) -> QLayout:
        from PyQt6.QtWidgets import QVBoxLayout
        layout = QVBoxLayout(ctx.container)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        return layout

    @staticmethod
    def create_title_widget(ctx: WidgetBuildContext):
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
        from formbridge.forms.layout_constants import CURRENT_LAYOUT

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

    @staticmethod
    def connect_checkbox_logic(manager, param_info, checkbox, nested_form, nested_manager, title_label, help_btn, unwrapped_type):
        """
        Handler for connecting optional dataclass checkbox toggle logic.

        Checkbox controls None vs instance state (independent of enabled field).
        """
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
                nested_manager.schedule_lifecycle_callback(
                    0,
                    lambda: nested_manager._enabled_field_styling_service.apply_initial_enabled_styling(
                        nested_manager
                    ),
                )
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

    def add_title(self, rt: WidgetCreationRuntime) -> None:
        self.title_components = self.create_title_widget(rt.ctx)
        rt.ctx.layout.addWidget(self.title_components.title_widget)
        rt.log_widget("title_widget", self.title_components.title_widget)
        rt.log_widget("presence_checkbox", self.title_components.checkbox)

    def place_widget(self, rt: WidgetCreationRuntime) -> None:
        super().place_widget(rt)
        rt.main_widget.setEnabled(rt.ctx.current_value is not None)

    def add_reset_button(self, rt: WidgetCreationRuntime) -> None:
        self.title_components.reset_all_button.clicked.connect(self.reset_callback(rt))

    def connect_structure(self, rt: WidgetCreationRuntime) -> None:
        title = self.title_components
        self.connect_checkbox_logic(
            rt.ctx.manager, rt.ctx.param_info, title.checkbox, rt.main_widget,
            rt.ctx.manager.nested_managers[rt.ctx.param_info.name],
            title.title_label, title.help_btn, rt.ctx.unwrapped_type,
        )


@dataclass
class WidgetCreationRuntime:
    """Mutable state for one widget-creation pipeline execution."""

    config: WidgetCreationConfig
    ctx: WidgetBuildContext
    create_seq: int
    main_widget: QWidget | None = None

    def log_widget(self, stage: str, widget: QWidget | None) -> None:
        rt = self
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
                type(rt.config).__name__,
                rt.ctx.param_info.name,
                rt.ctx.manager.config.field_id,
                rt.ctx.manager._pfm_seq,
                widget_class,
                widget_name,
                widget_id,
                parent_class,
            )
        except Exception:
            logger.debug("[WIDGET_CREATE] seq=%s stage=%s param=%s log_failed", rt.create_seq, stage, rt.ctx.param_info.name)


class WidgetCreationPipeline:
    """One shared lifecycle; the selected creation owner supplies every stage."""

    def __init__(self, manager: ParameterFormManager, param_info: ParameterInfo) -> None:
        config = WidgetCreationConfig.for_parameter(param_info)
        display_info = WidgetService.get_parameter_display_info(
            param_info.name,
            param_info.type,
            manager=manager,
            description=param_info.description,
        )
        field_ids = manager.service.generate_field_ids_direct(manager.config.field_id, param_info.name)
        current_value = manager.parameters.get(param_info.name)
        unwrapped_type = config.unwrapped_type(param_info)
        ctx = WidgetBuildContext(
            manager=manager,
            param_info=param_info,
            display_info=display_info,
            field_ids=field_ids,
            current_value=current_value,
            unwrapped_type=unwrapped_type,
            layout_config=CURRENT_LAYOUT,
        )
        self.runtime = WidgetCreationRuntime(
            config=config,
            ctx=ctx,
            create_seq=next(_WIDGET_CREATE_SEQ),
        )
        logger.debug("create_widget_parametric: config type=%s", type(config).__name__)

    def run(self) -> QWidget:
        self.create_container()
        rt = self.runtime
        with rt.config.content_update(rt):
            rt.config.configure_container(rt)
            rt.ctx = rt.ctx.with_layout(rt.config.create_layout(rt.ctx))
            rt.config.add_title(rt)
            self.create_main_widget()
            rt.config.place_widget(rt)
            rt.config.add_reset_controls(rt)
            rt.config.connect_structure(rt)
            rt.config.store_widget(rt, self.on_widget_change)
            rt.ctx.manager.chrome_sync.update_label_styling(rt.ctx.param_info.name)
        return rt.ctx.container

    def create_container(self) -> None:
        rt = self.runtime
        rt.ctx = rt.ctx.with_container(rt.config.create_container(rt.ctx))
        rt.log_widget("container", rt.ctx.container)

    def create_main_widget(self) -> None:
        rt = self.runtime
        rt.main_widget = rt.config.create_main_widget(rt.ctx)
        rt.log_widget("main_widget", rt.main_widget)

    def on_widget_change(self, pname, value) -> None:
        from objectstate import ObjectStateRegistry

        manager = self.runtime.ctx.manager
        converted_value = manager._convert_widget_value(value, pname)
        event = FieldChangeEvent(pname, converted_value, manager)
        if manager.state and manager.state._parent_state is not None:
            with ObjectStateRegistry.atomic(
                "edit parameter",
                scope_id=manager.scope_id,
            ):
                FieldChangeDispatcher.instance().dispatch(event)
        else:
            FieldChangeDispatcher.instance().dispatch(event)
