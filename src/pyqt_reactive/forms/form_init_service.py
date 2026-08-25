"""
Consolidated Form Initialization Service.

Merges:
- InitializationServices: Metaprogrammed initialization services for ParameterFormManager
- InitializationStepFactory: Factory for creating initialization step services
- FormBuildOrchestrator: root-scoped progressive widget construction

Key features:
1. Auto-generates service classes from builder functions using decorator-based registry
2. Unified async/sync widget creation paths
3. Ordered callback execution (styling → placeholders → enabled styling)
4. One semantic finalization after a complete root form generation
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, make_dataclass, fields as dataclass_fields
from enum import Enum, auto
from time import perf_counter
from typing import TYPE_CHECKING, Any, Dict, Optional, Type, Callable, List, TypeVar
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QVBoxLayout, QWidget
import inspect
import sys
from abc import ABC
import logging
from contextlib import contextmanager

from python_introspect import UnifiedParameterAnalyzer
from pyqt_reactive.forms.parameter_form_base import ParameterFormConfig
from pyqt_reactive.forms.parameter_form_constants import CONSTANTS
from pyqt_reactive.forms.parameter_value_contracts import (
    FormContext,
    FormObject,
    GeneratedServiceNamespace,
    ParameterDefaultsByName,
    ParameterDescriptionByPath,
    ParameterDescriptionProvider,
    ParameterInfoSequence,
)
from pyqt_reactive.theming.color_scheme import ColorScheme as PyQt6ColorScheme
from objectstate import get_base_config_type, has_lazy_resolution

if TYPE_CHECKING:
    from pyqt_reactive.forms.parameter_form_service import FormStructure

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
    default_value: ParameterDefaultsByName = field(
        default_factory=ParameterDefaultsByName,
        metadata={'initial_values': True, 'project': lambda name, info, field_id: (name, info.default_value)}
    )
    param_type: Dict[str, Type] = field(
        default_factory=dict,
        metadata={'project': lambda name, info, field_id: (name, info.param_type)}
    )
    # description can be a Dict[str, str] or a callable that returns Dict[str, str]
    # This allows lazy retrieval from ObjectState._parameter_descriptions to avoid timing issues
    description: ParameterDescriptionByPath | ParameterDescriptionProvider = field(
        default_factory=ParameterDescriptionByPath,
        metadata={
            'project': lambda name, info, field_id: (
                f"{field_id}.{name}" if field_id else name,
                info.description,
            )
        }
    )
    object_instance: FormObject | None = field(default=None, metadata={'computed': lambda obj, *_: obj})


@dataclass
class ConfigBuildResult:
    """Result of ConfigBuilderService.build() - bundles config + analysis."""
    config: ParameterFormConfig
    form_structure: 'FormStructure'
    global_config_type: Type
    placeholder_prefix: str


@dataclass
class DerivationContext:
    """Context for computing derived config values via properties."""
    context_obj: ParameterFormConfig | FormContext | None
    extracted: ExtractedParameters
    color_scheme: PyQt6ColorScheme | None

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
        return bool(obj_type and has_lazy_resolution(obj_type))

    @property
    def is_global_config_editing(self) -> bool:
        return not self.is_lazy_dataclass


@dataclass(frozen=True, slots=True)
class BuildConfig:
    """Root-scoped progressive form construction policy."""

    initial_sync_widgets: int = 5
    max_widgets_per_slice: int = 3
    max_slice_ms: float = 12.0

    def __post_init__(self) -> None:
        if self.initial_sync_widgets < 0:
            raise ValueError("initial_sync_widgets must be non-negative.")
        if self.max_widgets_per_slice < 1:
            raise ValueError("max_widgets_per_slice must be positive.")
        if self.max_slice_ms <= 0:
            raise ValueError("max_slice_ms must be positive.")


class FormBuildState(Enum):
    """Single lifecycle authority for one root form construction."""

    ACTIVE = auto()
    COMPLETED = auto()
    CANCELLED = auto()
    FAILED = auto()


@dataclass(slots=True)
class ProgressiveFormWork:
    """Remaining row construction for one manager."""

    manager: Any
    content_layout: QVBoxLayout
    param_infos: ParameterInfoSequence
    on_batch_complete: Callable[[list[tuple[str, QWidget]]], None]
    index: int = 0


class FormBuildTransaction:
    """Own one root form's progressive construction and finalization.

    Nested managers share this transaction. The initial synchronous allowance
    is therefore spent once for the whole form tree instead of once per nested
    manager. A generation is finalized only after the root has registered all
    construction work and every asynchronous manager has completed.
    """

    def __init__(self, root_manager, config: BuildConfig | None = None) -> None:
        self.root_manager = root_manager
        self.config = config or BuildConfig()
        self._remaining_sync_widgets = self.config.initial_sync_widgets
        self._registration_depth = 0
        self._pending_managers: dict[int, Any] = {}
        self._work_queue: deque[ProgressiveFormWork] = deque()
        self._root_registered = False
        self._finalization_scheduled = False
        self._state = FormBuildState.ACTIVE
        self.failure: Exception | None = None
        self.finalization_count = 0
        self.max_slice_elapsed_s = 0.0
        self._work_timer = QTimer(root_manager)
        self._work_timer.setSingleShot(True)
        self._work_timer.timeout.connect(self._run_next_slice)
        root_manager.destroyed.connect(self.cancel)

    def begin_registration(self) -> None:
        if self._state is not FormBuildState.ACTIVE:
            raise RuntimeError("Cannot register form work after finalization.")
        self._registration_depth += 1

    @property
    def complete(self) -> bool:
        """Whether the root form has completed semantic finalization."""
        return self._state is FormBuildState.COMPLETED

    @property
    def cancelled(self) -> bool:
        """Whether the lifecycle owner cancelled unfinished construction."""
        return self._state is FormBuildState.CANCELLED

    def claim_initial_sync_widgets(self, requested: int) -> int:
        claimed = min(max(requested, 0), self._remaining_sync_widgets)
        self._remaining_sync_widgets -= claimed
        return claimed

    def enqueue_async_manager(
        self,
        manager,
        content_layout: QVBoxLayout,
        param_infos: ParameterInfoSequence,
        on_batch_complete: Callable[[list[tuple[str, QWidget]]], None],
    ) -> None:
        """Register one manager and queue its remaining rows."""
        if self._state is not FormBuildState.ACTIVE:
            raise RuntimeError("Cannot enqueue form work after finalization.")
        self._pending_managers[id(manager)] = manager
        self._work_queue.append(
            ProgressiveFormWork(
                manager=manager,
                content_layout=content_layout,
                param_infos=param_infos,
                on_batch_complete=on_batch_complete,
            )
        )
        self._schedule_work()

    def finish_registration(self, manager) -> None:
        if self._registration_depth <= 0:
            raise RuntimeError("Unbalanced form build registration.")
        self._registration_depth -= 1
        if manager is self.root_manager:
            self._root_registered = True
        self._schedule_finalization_if_complete()

    def complete_async_manager(self, manager) -> None:
        manager_id = id(manager)
        if manager_id not in self._pending_managers:
            raise RuntimeError(
                f"Form manager completed without pending work: {manager.field_id!r}"
            )
        del self._pending_managers[manager_id]
        self._schedule_finalization_if_complete()

    def fail(self, error: Exception) -> None:
        """Stop this generation and publish its construction failure once."""
        if self._state is not FormBuildState.ACTIVE:
            return
        self.failure = error
        self._state = FormBuildState.FAILED
        self._work_timer.stop()
        self._work_queue.clear()
        self._pending_managers.clear()
        self.root_manager.form_build_failed.emit(error)

    def cancel(self, _destroyed_object: object | None = None) -> None:
        """Stop unfinished work without projecting teardown as a build failure."""
        if self._state is not FormBuildState.ACTIVE:
            return
        self._state = FormBuildState.CANCELLED
        self._work_timer.stop()
        self._work_queue.clear()
        self._pending_managers.clear()

    def _schedule_work(self) -> None:
        if (
            self._state is FormBuildState.ACTIVE
            and self._work_queue
            and not self._work_timer.isActive()
        ):
            self._work_timer.start(0)

    def _run_next_slice(self) -> None:
        if self._state is not FormBuildState.ACTIVE:
            return
        slice_started = perf_counter()
        widgets_created = 0
        batch_widgets: dict[int, tuple[ProgressiveFormWork, list]] = {}

        while self._work_queue:
            work = self._work_queue.popleft()
            try:
                parent = work.content_layout.parentWidget()
            except RuntimeError:
                return
            if parent is None:
                return

            param_info = work.param_infos[work.index]
            try:
                widget = work.manager._create_widget_for_param(param_info)
                work.content_layout.addWidget(widget)
            except Exception as error:
                logger.exception(
                    "Progressive form construction failed for %s",
                    work.manager.field_id,
                )
                self.fail(error)
                return

            work.index += 1
            widgets_created += 1
            entry = batch_widgets.setdefault(id(work), (work, []))
            entry[1].append((param_info.name, widget))

            if work.index < len(work.param_infos):
                self._work_queue.append(work)
            else:
                self.complete_async_manager(work.manager)

            elapsed_ms = (perf_counter() - slice_started) * 1000
            if (
                widgets_created >= self.config.max_widgets_per_slice
                or elapsed_ms >= self.config.max_slice_ms
            ):
                break

        for work, widgets in batch_widgets.values():
            try:
                work.on_batch_complete(widgets)
            except Exception as error:
                logger.exception(
                    "Progressive form batch callback failed for %s",
                    work.manager.field_id,
                )
                self.fail(error)
                return

        self.max_slice_elapsed_s = max(
            self.max_slice_elapsed_s,
            perf_counter() - slice_started,
        )
        self._schedule_work()

    def _schedule_finalization_if_complete(self) -> None:
        if (
            not self._root_registered
            or self._registration_depth
            or self._pending_managers
            or self._finalization_scheduled
            or self._state is not FormBuildState.ACTIVE
        ):
            return
        self._finalization_scheduled = True
        self.root_manager.schedule_lifecycle_callback(0, self._finalize)

    def _finalize(self) -> None:
        self._finalization_scheduled = False
        if (
            self._registration_depth
            or self._pending_managers
            or self._state is not FormBuildState.ACTIVE
        ):
            self._schedule_finalization_if_complete()
            return
        try:
            FormBuildOrchestrator()._execute_post_build_sequence(self.root_manager)
        except Exception as error:
            logger.exception("Form generation finalization failed.")
            self.fail(error)
            return
        self._state = FormBuildState.COMPLETED
        self.finalization_count += 1
        self.root_manager.form_build_completed.emit()


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

    def install_generated_services(self, namespace: GeneratedServiceNamespace) -> None:
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

# Import service modules explicitly so the services package has no runtime export dispatch.
import pyqt_reactive.services.widget_service as widget_service
import pyqt_reactive.services.value_collection_service as value_collection_service
import pyqt_reactive.services.signal_service as signal_service
import pyqt_reactive.services.parameter_ops_service as parameter_ops_service
import pyqt_reactive.services.enabled_field_styling_service as enabled_field_styling_service
import pyqt_reactive.services.enum_dispatch_service as enum_dispatch_service


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
    """Orchestrate a root transaction's progressive widget construction."""

    @staticmethod
    def is_root_manager(manager) -> bool:
        return manager._parent_manager is None

    @staticmethod
    def is_nested_manager(manager) -> bool:
        return manager._parent_manager is not None

    def build_widgets(
        self,
        manager,
        content_layout: QVBoxLayout,
        param_infos: ParameterInfoSequence,
    ) -> None:
        """Register and build one manager within its root transaction."""
        pass  # timer decorator - optional

        transaction = manager._form_build_transaction
        transaction.begin_registration()
        try:
            sync_count = transaction.claim_initial_sync_widgets(len(param_infos))
            sync_params = param_infos[:sync_count]
            async_params = param_infos[sync_count:]
            logger.debug(
                "[BUILD_WIDGETS] field_id=%s sync_count=%s async_count=%s "
                "param_count=%s manager_seq=%s",
                manager.field_id,
                len(sync_params),
                len(async_params),
                len(param_infos),
                manager._pfm_seq,
            )

            if sync_params:
                with timer(
                    f"        Create {len(sync_params)} initial widgets (sync)",
                    threshold_ms=5.0,
                ):
                    for param_info in sync_params:
                        logger.debug(
                            "[BUILD_WIDGETS_ASYNC] phase=sync field_id=%s "
                            "param=%s manager_seq=%s",
                            manager.field_id,
                            param_info.name,
                            manager._pfm_seq,
                        )
                        widget = manager._create_widget_for_param(param_info)
                        content_layout.addWidget(widget)
                manager.chrome_sync.fields_materialized(
                    param_info.name for param_info in sync_params
                )

            def on_batch_complete(batch_widgets):
                logger.debug(
                    "[BATCH_COMPLETE] field_id=%s batch_widgets=%s manager_seq=%s",
                    manager.field_id,
                    len(batch_widgets),
                    manager._pfm_seq,
                )
                manager.chrome_sync.fields_materialized(
                    param_name for param_name, _widget in batch_widgets
                )

            if async_params:
                transaction.enqueue_async_manager(
                    manager,
                    content_layout,
                    async_params,
                    on_batch_complete=on_batch_complete,
                )
        except Exception as error:
            transaction.fail(error)
            raise
        finally:
            transaction.finish_registration(manager)

    def _execute_post_build_sequence(self, manager) -> None:
        """Finalize one complete root form generation exactly once."""
        pass  # timer decorator - optional

        if self.is_nested_manager(manager):
            raise ValueError("Form generation finalization requires the root manager.")

        managers = tuple(self._walk_managers(manager))

        with timer("  Apply styling callbacks", threshold_ms=5.0):
            for form_manager in managers:
                self._apply_callbacks(form_manager._on_build_complete_callbacks)

        with timer("  Complete placeholder refresh", threshold_ms=10.0):
            logger.debug(
                "[POST_BUILD] ROOT refresh_with_live_context field_id=%s manager_seq=%s",
                manager.field_id,
                manager._pfm_seq,
            )
            manager._parameter_ops_service.refresh_with_live_context(manager)

        with timer("  Apply post-placeholder callbacks", threshold_ms=5.0):
            for form_manager in managers:
                self._apply_callbacks(
                    form_manager._on_placeholder_refresh_complete_callbacks
                )

        # Initialize semantic indicators for all labels and compound widgets
        # based on current state. This handles forms that open with pre-existing
        # dirty fields or signature-default overrides.
        with timer("  Initialize semantic indicators", threshold_ms=5.0):
            self._initialize_semantic_indicators(manager)

    @classmethod
    def _walk_managers(cls, manager):
        yield manager
        for nested_manager in manager.nested_managers.values():
            yield from cls._walk_managers(nested_manager)

    def _initialize_semantic_indicators(self, manager) -> None:
        """Initialize dirty/default chrome in manager and nested managers."""
        if not manager.state.dirty_fields and not manager.state.signature_diff_fields:
            return
        for param_name in manager.labels:
            manager.chrome_sync.update_label_styling(param_name)
        for param_name in manager.widgets:
            manager.chrome_sync.update_label_styling(param_name)
        for nested_manager in manager.nested_managers.values():
            self._initialize_semantic_indicators(nested_manager)

    @staticmethod
    def _apply_callbacks(callback_list: List[Callable]) -> None:
        for callback in callback_list:
            callback()
        callback_list.clear()
