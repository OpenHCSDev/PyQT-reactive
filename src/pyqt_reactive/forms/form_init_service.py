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
from pyqt_reactive.forms.parameter_form_constants import CONSTANTS
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
    default_value: Dict[str, Any] = field(
        default_factory=dict,
        metadata={'initial_values': True, 'project': lambda name, info, field_id: (name, info.default_value)}
    )
    param_type: Dict[str, Type] = field(
        default_factory=dict,
        metadata={'project': lambda name, info, field_id: (name, info.param_type)}
    )
    # description can be a Dict[str, str] or a callable that returns Dict[str, str]
    # This allows lazy retrieval from ObjectState._parameter_descriptions to avoid timing issues
    description: Any = field(
        default_factory=dict,
        metadata={
            'project': lambda name, info, field_id: (
                f"{field_id}.{name}" if field_id else name,
                info.description,
            )
        }
    )
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
        if isinstance(self.context_obj, ParameterFormConfig) and self.context_obj.global_config_type is not None:
            return self.context_obj.global_config_type
        return get_base_config_type()

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

@dataclass(frozen=True)
class BuilderSpec:
    """Builder declaration before a generated service type exists."""

    output_type: Type
    service_name: str
    builder_func: Callable


@dataclass(frozen=True)
class GeneratedServiceLineage:
    """Exact lineage for a generated initialization service class."""

    service_type: Type
    output_type: Type
    service_name: str
    builder_func: Callable


class InitializationServiceCatalog:
    """Generated initialization-service family with explicit lineage authority."""

    def __init__(self) -> None:
        self._builders_by_output: Dict[Type, BuilderSpec] = {}
        self._lineage_by_output: Dict[Type, GeneratedServiceLineage] = {}
        self._lineage_by_generated: Dict[Type, GeneratedServiceLineage] = {}

    def builder_for(self, output_type: Type, service_name: str):
        """Decorator to register builder function and auto-generate service class."""
        def decorator(func: Callable) -> Callable:
            self._builders_by_output[output_type] = BuilderSpec(output_type, service_name, func)
            return func
        return decorator

    def install_generated_services(self, namespace: Dict[str, Any]) -> None:
        """Generate all registered services into a module namespace."""
        for spec in self._builders_by_output.values():
            namespace[spec.service_name] = self._create_service_type(spec)

    def lineage_for_output(self, output_type: Type) -> Optional[GeneratedServiceLineage]:
        return self._lineage_by_output.get(output_type)

    def lineage_for_generated(self, service_type: Type) -> Optional[GeneratedServiceLineage]:
        return self._lineage_by_generated.get(service_type)

    def normalize_generated_service(self, service_or_output_type: Type) -> Type:
        """Return the generated service type for a generated service or its output type."""
        lineage = (
            self.lineage_for_generated(service_or_output_type)
            or self.lineage_for_output(service_or_output_type)
        )
        if lineage is None:
            raise KeyError(
                "Type is not part of the initialization service family: "
                f"{service_or_output_type!r}"
            )
        return lineage.service_type

    def _create_service_type(self, spec: BuilderSpec) -> Type:
        """Create a service class with a .build() method and recorded lineage."""
        def build(*args, **kwargs) -> spec.output_type:
            return spec.builder_func(*args, **kwargs)

        service_type = type(spec.service_name, (), {
            'build': staticmethod(build),
            '__doc__': f"{spec.service_name} - Metaprogrammed initialization step. Returns: {spec.output_type.__name__}",
            '_output_type': spec.output_type,
            '_builder_func': spec.builder_func,
        })
        self._record_lineage(spec, service_type)
        return service_type

    def _record_lineage(self, spec: BuilderSpec, service_type: Type) -> None:
        lineage = GeneratedServiceLineage(
            service_type=service_type,
            output_type=spec.output_type,
            service_name=spec.service_name,
            builder_func=spec.builder_func,
        )
        self._lineage_by_output[spec.output_type] = lineage
        self._lineage_by_generated[service_type] = lineage


INITIALIZATION_SERVICES = InitializationServiceCatalog()


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

        for _, attr in inspect.getmembers(current_module, inspect.ismodule):
            if not inspect.ismodule(attr):
                continue

            module_name = attr.__name__.split('.')[-1]
            class_name = ''.join(word.capitalize() for word in module_name.split('_'))

            module_classes = dict(inspect.getmembers(attr, inspect.isclass))
            service_class = module_classes.get(class_name)
            if service_class is None or inspect.isabstract(service_class):
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
            projection = fld.metadata.get('project')
            if projection is None:
                raise ValueError(f"Unsupported extracted parameter field: {fld.name}")
            extracted[fld.name] = dict(
                projection(name, info, field_id)
                for name, info in param_info_dict.items()
            )
            if initial_values and fld.metadata.get('initial_values'):
                extracted[fld.name].update(initial_values)

        return ExtractedParameters(**extracted, **computed)

    def _build_config(field_id, extracted, context_obj, color_scheme, parent_manager, service, form_manager_config=None):
        # CRITICAL: Nested managers should NOT create scroll areas
        # Only root managers (parent_manager is None) should have scroll areas
        is_nested = parent_manager is not None

        if form_manager_config:
            use_scroll_area = form_manager_config.use_scroll_area
        else:
            use_scroll_area = not is_nested  # Default: only root managers get scroll areas

        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"🔧 Building config for {field_id}: is_nested={is_nested}, use_scroll_area={use_scroll_area}")

        obj_type = type(extracted.object_instance) if extracted.object_instance else None
        function_target = (
            form_manager_config.function_target
            if form_manager_config and form_manager_config.function_target is not None
            else obj_type
        )
        config = ParameterFormConfig(
            field_id=field_id,
            framework=CONSTANTS.PYQT6_FRAMEWORK,
            color_scheme=color_scheme or PyQt6ColorScheme(),
            function_target=function_target,
            use_scroll_area=use_scroll_area
        )

        ctx = DerivationContext(context_obj, extracted, color_scheme)
        vars(config).update(vars(ctx))

        from pyqt_reactive.forms.parameter_form_service import ParameterAnalysisInput
        description = extracted.description
        analysis_input = ParameterAnalysisInput(
            field_id=field_id,
            parent_obj_type=obj_type,
            default_value=extracted.default_value,
            param_type=extracted.param_type,
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

    INITIALIZATION_SERVICES.builder_for(ExtractedParameters, 'ParameterExtractionService')(_extract_parameters)
    INITIALIZATION_SERVICES.builder_for(ParameterFormConfig, 'ConfigBuilderService')(_build_config)
    INITIALIZATION_SERVICES.builder_for(ManagerServices, 'ServiceFactoryService')(_create_services)


_auto_generate_builders()

INITIALIZATION_SERVICES.install_generated_services(globals())


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
            manager._pfm_seq,
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
                        manager._pfm_seq,
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

        if sync_params:
            with timer(f"        Create {len(sync_params)} initial widgets (sync)", threshold_ms=5.0):
                for param_info in sync_params:
                    logger.debug(
                        "[BUILD_WIDGETS_ASYNC] phase=sync field_id=%s param=%s manager_seq=%s",
                        manager.field_id,
                        param_info.name,
                        manager._pfm_seq,
                    )
                    widget = manager._create_widget_for_param(param_info)
                    content_layout.addWidget(widget)

        def on_batch_complete(batch_widgets):
            logger.debug(
                "[BATCH_COMPLETE] field_id=%s batch_widgets=%s manager_seq=%s",
                manager.field_id,
                len(batch_widgets),
                manager._pfm_seq,
            )

        def on_async_complete():
            logger.debug(
                "[ASYNC_COMPLETE] field_id=%s widgets=%s is_nested=%s manager_seq=%s",
                manager.field_id,
                len(manager.widgets),
                self.is_nested_manager(manager),
                manager._pfm_seq,
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
            nested_manager._pfm_seq,
            root_manager.field_id,
            root_manager._pfm_seq,
        )

    def _execute_post_build_sequence(self, manager) -> None:
        """Execute standard post-build callback sequence."""
        pass  # timer decorator - optional

        if self.is_nested_manager(manager):
            logger.debug(
                "[POST_BUILD] NESTED field_id=%s widgets=%s callback_count=%s manager_seq=%s",
                manager.field_id,
                len(manager.widgets),
                len(manager._on_build_complete_callbacks),
                manager._pfm_seq,
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
                manager._pfm_seq,
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
            manager.chrome_sync.update_label_styling(param_name)
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
