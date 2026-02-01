"""
Consolidated Form Initialization Service.

Merges:
- InitializationServices: Metaprogrammed initialization services for ParameterFormManager
- InitializationStepFactory: Factory for creating initialization step services
- FormBuildOrchestrator: Async/sync widget creation orchestration
- InitialRefreshStrategy: Enum-driven dispatch for initial placeholder refresh

Key features:
1. Auto-generates service classes from builder functions using decorator-based registry
2. Unified async/sync widget creation paths
3. Ordered callback execution (styling → placeholders → enabled styling)
4. Enum-driven dispatch for initial refresh strategy
"""

from dataclasses import dataclass, field, make_dataclass, fields as dataclass_fields
from typing import Any, Dict, Optional, Type, Callable, List, TypeVar
from enum import Enum, auto
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from PyQt6.QtCore import QTimer
import inspect
import sys
from abc import ABC
import logging
from contextlib import contextmanager

from python_introspect import UnifiedParameterAnalyzer
from pyqt_reactive.forms.parameter_form_base import ParameterFormConfig
from pyqt_reactive.theming.color_scheme import ColorScheme as PyQt6ColorScheme
from objectstate import get_base_config_type

try:
    from pyqt_reactive.core.performance_monitor import timer
except Exception:  # pragma: no cover - optional performance monitoring
    @contextmanager
    def timer(*args, **kwargs):
        yield

logger = logging.getLogger(__name__)
T = TypeVar('T')


# ============================================================================
# Output Dataclasses
# ============================================================================

@dataclass
class ExtractedParameters:
    """Result of parameter extraction from object_instance."""
    default_value: Dict[str, Any] = field(default_factory=dict, metadata={'initial_values': True})
    param_type: Dict[str, Type] = field(default_factory=dict)
    # description can be a Dict[str, str] or a callable that returns Dict[str, str]
    # This allows lazy retrieval from ObjectState._parameter_descriptions to avoid timing issues
    description: Any = field(default_factory=dict)
    object_instance: Any = field(default=None, metadata={'computed': lambda obj, *_: obj})


@dataclass
class ConfigBuildResult:
    """Result of ConfigBuilderService.build() - bundles config + analysis."""
    config: Any  # The real ParameterFormConfig from parameter_form_base
    form_structure: Any
    global_config_type: Type
    placeholder_prefix: str


@dataclass
class DerivationContext:
    """Context for computing derived config values via properties."""
    context_obj: Any
    extracted: ExtractedParameters
    color_scheme: Any

    @property
    def global_config_type(self) -> Type:
        return getattr(self.context_obj, 'global_config_type', get_base_config_type())

    @property
    def placeholder_prefix(self) -> str:
        return "Pipeline default"

    @property
    def is_lazy_dataclass(self) -> bool:
        obj_type = type(self.extracted.object_instance) if self.extracted.object_instance else None
        return obj_type and LazyDefaultPlaceholderService.has_lazy_resolution(obj_type)

    @property
    def is_global_config_editing(self) -> bool:
        return not self.is_lazy_dataclass


# ============================================================================
# Build Configuration
# ============================================================================

class BuildPhase(Enum):
    """Phases of form building process."""
    WIDGET_CREATION = "widget_creation"
    STYLING_CALLBACKS = "styling_callbacks"
    PLACEHOLDER_REFRESH = "placeholder_refresh"
    POST_PLACEHOLDER_CALLBACKS = "post_placeholder_callbacks"
    ENABLED_STYLING = "enabled_styling"


class RefreshMode(Enum):
    """Refresh modes for initial placeholder refresh."""
    ROOT_GLOBAL_CONFIG = auto()
    OTHER_WINDOW = auto()


@dataclass
class BuildConfig:
    """Configuration for form building."""
    initial_sync_widgets: int = 5
    use_async_threshold: int = 5


# ============================================================================
# Builder Registry
# ============================================================================

_BUILDER_REGISTRY: Dict[Type, tuple[str, Callable]] = {}


def builder_for(output_type: Type, service_name: str):
    """Decorator to register builder function and auto-generate service class."""
    def decorator(func: Callable) -> Callable:
        _BUILDER_REGISTRY[output_type] = (service_name, func)
        return func
    return decorator


# ============================================================================
# Initialization Step Factory
# ============================================================================

class InitializationStepFactory:
    """Factory for creating metaprogrammed initialization step services."""
    
    @staticmethod
    def create_step(name: str, output_type: Type[T], builder_func: Callable[..., T]) -> Type:
        """Create a service class with a .build() method."""
        def build(*args, **kwargs) -> output_type:
            return builder_func(*args, **kwargs)
        
        return type(name, (), {
            'build': staticmethod(build),
            '__doc__': f"{name} - Metaprogrammed initialization step. Returns: {output_type.__name__}",
            '_output_type': output_type,
            '_builder_func': builder_func,
        })


# ============================================================================
# Service Registry Meta
# ============================================================================

# Import service modules
from pyqt_reactive.services import (
    widget_service,
    value_collection_service,
    signal_service,
    parameter_ops_service,
    enabled_field_styling_service,
    enum_dispatch_service,
)


class ServiceRegistryMeta(type):
    """Metaclass that auto-discovers service classes from imported modules."""

    def __new__(mcs, name, bases, namespace):
        current_module = sys.modules[__name__]
        service_fields = [('service', type(None), field(default=None))]

        for attr_name in dir(current_module):
            attr = getattr(current_module, attr_name)
            if not inspect.ismodule(attr):
                continue

            module_name = attr.__name__.split('.')[-1]
            class_name = ''.join(word.capitalize() for word in module_name.split('_'))

            if hasattr(attr, class_name):
                service_class = getattr(attr, class_name)
                if inspect.isabstract(service_class):
                    continue
                service_fields.append((module_name, service_class, field(default=None)))

        return make_dataclass(name, service_fields)


class ManagerServices(metaclass=ServiceRegistryMeta):
    """Auto-generated dataclass - fields created by ServiceRegistryMeta."""
    pass


# ============================================================================
# Builder Functions
# ============================================================================

def _auto_generate_builders():
    """Auto-generate all builder functions via introspection of their output types."""

    def _extract_parameters(object_instance, exclude_params, initial_values, field_id=None):
        param_info_dict = UnifiedParameterAnalyzer.analyze(object_instance, exclude_params=exclude_params or [])
        extracted = {}
        computed = {}
 
        for fld in dataclass_fields(ExtractedParameters):
            if 'computed' in fld.metadata:
                computed[fld.name] = fld.metadata['computed'](object_instance, exclude_params, initial_values)
                continue
            if fld.name == "description":
                prefix = f'{field_id}.' if field_id else ''
                extracted[fld.name] = {f'{prefix}{name}': getattr(info, "description", None) for name, info in param_info_dict.items()}
            else:
                extracted[fld.name] = {name: getattr(info, fld.name) for name, info in param_info_dict.items()}
            if initial_values and fld.metadata.get('initial_values'):
                extracted[fld.name].update(initial_values)
 
        return ExtractedParameters(**extracted, **computed)

    def _build_config(field_id, extracted, context_obj, color_scheme, parent_manager, service, form_manager_config=None):
        # CRITICAL: Nested managers should NOT create scroll areas
        # Only root managers (parent_manager is None) should have scroll areas
        is_nested = parent_manager is not None

        # Check for use_scroll_area override from FormManagerConfig or from_dataclass_instance
        # This allows config window and step editor to disable scroll area creation
        if form_manager_config:
            # Check new API (FormManagerConfig.use_scroll_area field)
            if hasattr(form_manager_config, 'use_scroll_area') and form_manager_config.use_scroll_area is not None:
                use_scroll_area = form_manager_config.use_scroll_area
            # Check old API (temporary _use_scroll_area_override attribute)
            elif hasattr(form_manager_config, '_use_scroll_area_override'):
                use_scroll_area = form_manager_config._use_scroll_area_override
            else:
                use_scroll_area = not is_nested  # Default: only root managers get scroll areas
        else:
            use_scroll_area = not is_nested  # Default: only root managers get scroll areas

        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"🔧 Building config for {field_id}: is_nested={is_nested}, use_scroll_area={use_scroll_area}")

        obj_type = type(extracted.object_instance) if extracted.object_instance else None
        config = ParameterFormConfig.for_pyqt(
            field_id=field_id,
            color_scheme=color_scheme or PyQt6ColorScheme(),
            function_target=obj_type,
            use_scroll_area=use_scroll_area
        )

        ctx = DerivationContext(context_obj, extracted, color_scheme)
        vars(config).update(vars(ctx))

        from pyqt_reactive.forms.parameter_form_service import ParameterAnalysisInput
        description = getattr(extracted, 'description', None)
        analysis_input = ParameterAnalysisInput(
            field_id=field_id,
            parent_obj_type=obj_type,
            default_value=getattr(extracted, 'default_value', {}),
            param_type=getattr(extracted, 'param_type', {}),
            description=description,
        )
        form_structure = service.analyze_parameters(analysis_input)

        return ConfigBuildResult(config, form_structure, ctx.global_config_type, ctx.placeholder_prefix)

    def _create_services():
        services = {}
        for fld in dataclass_fields(ManagerServices):
            if fld.type is type(None):
                services[fld.name] = fld.default
                continue
            try:
                services[fld.name] = fld.type()
            except TypeError:
                services[fld.name] = None

        return ManagerServices(**services)

    builder_for(ExtractedParameters, 'ParameterExtractionService')(_extract_parameters)
    builder_for(ParameterFormConfig, 'ConfigBuilderService')(_build_config)
    builder_for(ManagerServices, 'ServiceFactoryService')(_create_services)


_auto_generate_builders()

# Auto-generate service classes from registry
for output_type, (service_name, builder_func) in _BUILDER_REGISTRY.items():
    service_class = InitializationStepFactory.create_step(service_name, output_type, builder_func)
    globals()[service_name] = service_class


# ============================================================================
# Form Build Orchestrator
# ============================================================================

class FormBuildOrchestrator:
    """Orchestrates form building with unified async/sync paths."""

    def __init__(self, config: BuildConfig = None):
        self.config = config or BuildConfig()

    @staticmethod
    def is_root_manager(manager) -> bool:
        return manager._parent_manager is None

    @staticmethod
    def is_nested_manager(manager) -> bool:
        return manager._parent_manager is not None

    def build_widgets(self, manager, content_layout: QVBoxLayout, param_infos: List[Any], use_async: bool) -> None:
        """Build widgets using unified async/sync path."""
        pass  # timer decorator - optional

        logger.debug(
            "[BUILD_WIDGETS] field_id=%s use_async=%s param_count=%s manager_seq=%s",
            manager.field_id,
            use_async,
            len(param_infos),
            getattr(manager, '_pfm_seq', None),
        )
        if use_async:
            self._build_widgets_async(manager, content_layout, param_infos)
        else:
            self._build_widgets_sync(manager, content_layout, param_infos)

    def _build_widgets_sync(self, manager, content_layout: QVBoxLayout, param_infos: List[Any]) -> None:
        """Synchronous widget creation path."""
        pass  # timer decorator - optional
        from .parameter_info_types import DirectDataclassInfo, OptionalDataclassInfo

        with timer(f"      Create {len(param_infos)} parameter widgets", threshold_ms=5.0):
            for param_info in param_infos:
                is_nested = isinstance(param_info, (DirectDataclassInfo, OptionalDataclassInfo))
                with timer(f"        Create widget for {param_info.name}", threshold_ms=2.0):
                    logger.debug(
                        "[BUILD_WIDGETS_SYNC] field_id=%s param=%s is_nested=%s manager_seq=%s",
                        manager.field_id,
                        param_info.name,
                        is_nested,
                        getattr(manager, '_pfm_seq', None),
                    )
                    widget = manager._create_widget_for_param(param_info)
                    content_layout.addWidget(widget)

        self._execute_post_build_sequence(manager)

    def _build_widgets_async(self, manager, content_layout: QVBoxLayout, param_infos: List[Any]) -> None:
        """Asynchronous widget creation path."""
        pass  # timer decorator - optional

        if self.is_root_manager(manager):
            manager._pending_nested_managers = {}

        sync_params = param_infos[:self.config.initial_sync_widgets]
        async_params = param_infos[self.config.initial_sync_widgets:]

        sync_widgets = []

        if sync_params:
            with timer(f"        Create {len(sync_params)} initial widgets (sync)", threshold_ms=5.0):
                for param_info in sync_params:
                    logger.debug(
                        "[BUILD_WIDGETS_ASYNC] phase=sync field_id=%s param=%s manager_seq=%s",
                        manager.field_id,
                        param_info.name,
                        getattr(manager, '_pfm_seq', None),
                    )
                    widget = manager._create_widget_for_param(param_info)
                    content_layout.addWidget(widget)
                    sync_widgets.append((param_info.name, widget))

            if sync_widgets:
                # Apply scope accent styling to sync widgets (progressive, so user sees colored borders immediately)
                dialog = self._get_dialog_from_layout(content_layout)
                if dialog and hasattr(dialog, '_apply_scope_accent_to_widgets'):
                    dialog._apply_scope_accent_to_widgets(sync_widgets)

        def on_batch_complete(batch_widgets):
            # Apply scope accent styling to batch widgets (progressive, so user sees colored borders immediately)
            dialog = self._get_dialog_from_layout(content_layout)
            logger.debug(
                "[BATCH_COMPLETE] field_id=%s batch_widgets=%s manager_seq=%s dialog=%s has_apply_method=%s",
                manager.field_id,
                len(batch_widgets),
                getattr(manager, '_pfm_seq', None),
                dialog.__class__.__name__ if dialog else None,
                hasattr(dialog, '_apply_scope_accent_to_widgets') if dialog else False,
            )
            if dialog and hasattr(dialog, '_apply_scope_accent_to_widgets'):
                logger.debug("[BATCH_COMPLETE] Calling _apply_scope_accent_to_widgets")
                dialog._apply_scope_accent_to_widgets(batch_widgets)

        def on_async_complete():
            logger.debug(
                "[ASYNC_COMPLETE] field_id=%s widgets=%s is_nested=%s manager_seq=%s",
                manager.field_id,
                len(manager.widgets),
                self.is_nested_manager(manager),
                getattr(manager, '_pfm_seq', None),
            )

            # Then notify parent (if this is nested) to track completion
            if self.is_nested_manager(manager):
                self._notify_root_of_completion(manager)
            else:
                # Root manager: trigger final refresh after all widgets complete
                # This is the single source of truth for when ALL async widget creation is done
                # Use 500ms delay to ensure all async batches have completed
                QTimer.singleShot(500, lambda: manager._parameter_ops_service.refresh_with_live_context(manager))

            # Also refresh this manager immediately for progressive display
            self._execute_post_build_sequence(manager)

        if async_params:
            manager._create_widgets_async(
                content_layout, async_params,
                on_complete=on_async_complete,
                on_batch_complete=on_batch_complete
            )
        else:
            on_async_complete()



    def _notify_root_of_completion(self, nested_manager) -> None:
        """Notify root manager that nested manager completed async build."""
        root_manager = nested_manager._parent_manager
        while root_manager._parent_manager is not None:
            root_manager = root_manager._parent_manager
        root_manager._on_nested_manager_complete(nested_manager)
        logger.debug(
            "[NESTED_COMPLETE] nested_field_id=%s nested_seq=%s root_field_id=%s root_seq=%s",
            nested_manager.field_id,
            getattr(nested_manager, '_pfm_seq', None),
            root_manager.field_id,
            getattr(root_manager, '_pfm_seq', None),
        )

    def _get_dialog_from_layout(self, layout) -> Any:
        """Get the dialog window from a layout."""
        widget = layout.parentWidget()
        while widget:
            if hasattr(widget, '_apply_scope_accent_to_widgets'):
                return widget
            widget = widget.parent()
        return None

    def _execute_post_build_sequence(self, manager) -> None:
        """Execute standard post-build callback sequence."""
        pass  # timer decorator - optional

        if self.is_nested_manager(manager):
            logger.debug(
                "[POST_BUILD] NESTED field_id=%s widgets=%s callback_count=%s manager_seq=%s",
                manager.field_id,
                len(manager.widgets),
                len(manager._on_build_complete_callbacks),
                getattr(manager, '_pfm_seq', None),
            )
            for callback in manager._on_build_complete_callbacks:
                callback()
            manager._on_build_complete_callbacks.clear()
            return

        with timer("  Apply styling callbacks", threshold_ms=5.0):
            self._apply_callbacks(manager._on_build_complete_callbacks)

        with timer("  Complete placeholder refresh", threshold_ms=10.0):
            # CRITICAL: Use defer=True to give async widget batches time to finish
            # This ensures placeholders are applied to all widgets, including those
            # created in final async batches
            logger.debug(
                "[POST_BUILD] ROOT refresh_with_live_context field_id=%s manager_seq=%s",
                manager.field_id,
                getattr(manager, '_pfm_seq', None),
            )
            manager._parameter_ops_service.refresh_with_live_context(manager, defer=True)

        with timer("  Apply post-placeholder callbacks", threshold_ms=5.0):
            self._apply_callbacks(manager._on_placeholder_refresh_complete_callbacks)
            for nested_manager in manager.nested_managers.values():
                self._apply_callbacks(nested_manager._on_placeholder_refresh_complete_callbacks)

        with timer("  Apply initial enabled styling", threshold_ms=5.0):
            # CRITICAL: Initial enabled styling is now handled by showEvent in the widget
            # (e.g., StepParameterEditorWidget.showEvent)
            # This ensures styling is applied AFTER the widget is visible and painted
            pass

        # Initialize dirty indicators for all labels based on current state
        # This handles the case where the form opens with pre-existing dirty state
        with timer("  Initialize dirty indicators", threshold_ms=5.0):
            self._initialize_dirty_indicators(manager)

    def _initialize_dirty_indicators(self, manager) -> None:
        """Initialize dirty indicators for all labels in manager and nested managers."""
        if not manager.state.dirty_fields:
            return
        # Refresh all labels in this manager
        for param_name in manager.labels:
            manager._update_label_styling(param_name)
        # Recursively initialize nested managers
        for nested_manager in manager.nested_managers.values():
            self._initialize_dirty_indicators(nested_manager)

    @staticmethod
    def _apply_callbacks(callback_list: List[Callable]) -> None:
        for callback in callback_list:
            callback()
        callback_list.clear()

    def should_use_async(self, param_count: int) -> bool:
        return param_count > self.config.use_async_threshold


# ============================================================================
# Initial Refresh Strategy
# ============================================================================

class InitialRefreshStrategy:
    """Enum-driven dispatch for initial placeholder refresh."""

    @staticmethod
    def execute(manager: Any) -> None:
        """Execute the appropriate refresh strategy for the manager."""
        pass  # timer decorator - optional

        is_root_global_config = (
            manager.config.is_global_config_editing and
            manager.global_config_type is not None and
            manager.context_obj is None
        )

        if is_root_global_config:
            with timer("  Root global config sibling inheritance refresh", threshold_ms=10.0):
                manager._parameter_ops_service.refresh_with_live_context(manager)
        else:
            with timer("  Initial live context refresh", threshold_ms=10.0):
                service = parameter_ops_service.ParameterOpsService()
                service.refresh_with_live_context(manager)
