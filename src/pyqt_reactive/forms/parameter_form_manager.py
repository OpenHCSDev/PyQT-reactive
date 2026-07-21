"""PyQt parameter form manager - VIEW layer for ObjectState MODEL."""

from dataclasses import dataclass, is_dataclass
import logging
from typing import Any, Dict, Type, Optional, List, Set, Callable, TYPE_CHECKING
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QScrollArea
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor

from pyqt_reactive.animation import FlashMixin
from pyqt_reactive.animation.flash_trace import flash_trace
# FlashableGroupBox not extracted - OpenHCS specific
from objectstate import (
    DataclassFieldAccess,
    DottedFieldPath,
    FieldAccessError,
    register_hierarchy_relationship,
    unregister_hierarchy_relationship,
)

if TYPE_CHECKING:
    from objectstate import ObjectState
    from pyqt_reactive.widgets.structural_table import StructuralFlashTarget

from .widget_creation_types import ParameterFormManager as ParameterFormManagerABC, _CombinedMeta
# timer decorator made optional
from .widget_operations import WidgetOperations
from .widget_strategies import create_pyqt6_widget
from .layout_constants import CURRENT_LAYOUT
from .parameter_form_chrome_sync import ParameterFormChromeSync
from .parameter_form_tree_index import ParameterFormTreeIndex
from pyqt_reactive.services.value_collection_service import ValueCollectionService
from pyqt_reactive.services.signal_service import SignalService
from pyqt_reactive.services.field_change_dispatcher import FieldChangeDispatcher, FieldChangeEvent
# LiveContextService deleted - functionality moved to ObjectStateRegistry
from pyqt_reactive.services.flag_context_manager import FlagContextManager
from .form_init_service import FormBuildOrchestrator
from pyqt_reactive.forms.parameter_info_types import ParameterInfo
from pyqt_reactive.forms.parameter_value_contracts import (
    FormContext,
    ParameterTypesByName,
    ParameterDefaultsByName,
    ParameterValue,
    WidgetValue,
)
from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.shared.config_tree_contracts import ConfigTreeFlashManager
from pyqt_reactive.services.window_navigation import FormNavigationManager
from contextlib import contextmanager

try:
    from pyqt_reactive.core.performance_monitor import timer
except Exception:  # pragma: no cover - optional performance monitoring
    @contextmanager
    def timer(*args, **kwargs):
        yield

logger = logging.getLogger(__name__)
_PFM_SEQ = 0
@dataclass
class FormManagerConfig:
    """
    Configuration for ParameterFormManager initialization.

    Consolidates 8 optional parameters into a single config object,
    reducing __init__ signature from 10 → 3 parameters (70% reduction).

    Follows OpenHCS dataclass-based configuration patterns.
    """
    parent: Optional[QWidget] = None
    context_obj: Optional[FormContext] = None
    exclude_params: Optional[List[str]] = None
    initial_values: Optional[ParameterDefaultsByName] = None
    parent_manager: Optional['ParameterFormManager'] = None
    read_only: bool = False
    scope_id: Optional[str] = None
    color_scheme: Optional[ColorScheme] = None
    # Windows that manage scrolling must set this explicitly.
    use_scroll_area: bool = False
    state: Optional['ObjectState'] = None  # ObjectState instance - if provided, PFM delegates to it
    field_id: str = ''  # Canonical dotted path id for this form (e.g., 'well_filter_config')
    render_enabled_in_header: bool = False  # If True, 'enabled' checkbox is rendered in container header, not as a form row
    scope_accent_color: Optional[QColor] = None  # Scope accent color for help buttons
    scope_step_index: Optional[int] = None  # Optional step index to align scope styling with pipeline order
    function_target: Optional[Callable | type] = None  # Callable/class documentation owner for parameter help


class FormTargetPathAccess:
    """Path resolver for form targets that may be dataclasses or object-backed."""

    @classmethod
    def raw_path(cls, root, field_path: str):
        current = root
        for part in tuple(part for part in field_path.split(".") if part):
            current = cls.raw_value(current, part)
        return current

    @classmethod
    def raw_value(cls, instance, field_name: str):
        if is_dataclass(type(instance)):
            return DataclassFieldAccess.raw_value(instance, field_name)

        if type(instance).__dictoffset__ == 0:
            raise FieldAccessError(
                f"{type(instance).__name__} has no addressable instance fields."
            )

        storage = vars(instance)
        if field_name not in storage:
            raise FieldAccessError(
                f"{type(instance).__name__}.{field_name} is not stored on the instance."
            )
        return storage[field_name]


class ParameterFormTypeResolver:
    """Resolve visible form field types from ObjectState and signature authorities."""

    @staticmethod
    def field_type(manager: "ParameterFormManager", field_name: str, signature_type: Type) -> Type:
        dotted_path = f"{manager.field_id}.{field_name}" if manager.field_id else field_name
        if not ParameterFormTypeResolver.path_has_children(manager.state.parameters, dotted_path):
            return signature_type

        state_type = manager.state.type_for_path(dotted_path)
        if isinstance(state_type, type) and is_dataclass(state_type):
            return state_type
        return signature_type

    @staticmethod
    def path_has_children(parameters: Dict[str, Any], dotted_path: str) -> bool:
        owner_path = DottedFieldPath(dotted_path)
        return any(
            owner_path.contains_path(path)
            for path in parameters
            if path != dotted_path
        )

    @staticmethod
    def scoped_parameters(state, field_id: str) -> ParameterDefaultsByName:
        """Project ObjectState's flat parameters into one form manager scope."""
        if not field_id:
            return ParameterDefaultsByName(
                (key, value) for key, value in state.parameters.items() if "." not in key
            )

        owner_path = DottedFieldPath(field_id)
        result = ParameterDefaultsByName()
        for path, value in state.parameters.items():
            if owner_path.contains_path(path) and path != field_id:
                suffix = path[len(field_id):]
                if not suffix.startswith("."):
                    continue
                remainder = suffix[1:]
                if "." not in remainder:
                    result[remainder] = value
        return result


class ParameterFormManager(
    QWidget,
    ParameterFormManagerABC,
    FlashMixin,
    ConfigTreeFlashManager,
    metaclass=_CombinedMeta,
):
    """
    React-quality reactive form manager for PyQt6.

    Inherits from both QWidget and ParameterFormManagerABC with combined metaclass.
    All abstract methods MUST be implemented by this class.

    This implementation leverages the new context management system and supports any object type:
    - Dataclasses (via dataclasses.fields())
    - ABC constructors (via inspect.signature())
    - Step objects (via attribute scanning)
    - Any object with parameters

    Key improvements:
    - Generic object introspection replaces manual parameter specification
    - Context-driven resolution using config_context() system
    - Automatic parameter extraction from object instances
    - Unified interface for all object types
    - Dramatically simplified constructor (4 parameters vs 12+)
    - React-style lifecycle hooks and reactive updates
    - Proper ABC inheritance with metaclass conflict resolution
    """

    parameter_changed = pyqtSignal(str, object)  # param_name, value

    # Cross-window context change signal (simplified API)
    # Args: (scope_id, field_path) - field_path is None for bulk refresh
    context_changed = pyqtSignal(str, str)  # scope_id, field_path

    # NOTE: Class-level cross-cutting concerns moved to LiveContextService:
    # - _active_form_managers -> LiveContextService._active_form_managers
    # - _external_listeners -> LiveContextService._external_listeners
    # - _live_context_token_counter -> LiveContextService._live_context_token_counter
    # - _live_context_cache -> LiveContextService._live_context_cache
    # - collect_live_context() -> LiveContextService.collect()
    # - register_external_listener() -> LiveContextService.register_external_listener()
    # - unregister_external_listener() -> LiveContextService.unregister_external_listener()
    # - trigger_global_cross_window_refresh() -> LiveContextService.trigger_global_refresh()

    # Class constants for UI preferences (moved from constructor parameters)
    DEFAULT_USE_SCROLL_AREA = False
    DEFAULT_PLACEHOLDER_PREFIX = "Default"
    DEFAULT_COLOR_SCHEME = None

    # Performance optimization: Skip expensive operations for nested configs
    OPTIMIZE_NESTED_WIDGETS = True

    # Performance optimization: Async widget creation for large forms
    ASYNC_WIDGET_CREATION = True  # Create widgets progressively to avoid UI blocking
    ASYNC_THRESHOLD = 5  # Minimum number of parameters to trigger async widget creation
    INITIAL_SYNC_WIDGETS = 10  # Number of widgets to create synchronously for fast initial render
    CROSS_WINDOW_PLACEHOLDER_REFRESH_MS = 20

    @classmethod
    def should_use_async(cls, param_count: int) -> bool:
        """Determine if async widget creation should be used based on parameter count."""
        return cls.ASYNC_WIDGET_CREATION and param_count > cls.ASYNC_THRESHOLD

    # ========== STATE DELEGATION PROPERTIES ==========
    # ObjectState is single source of truth - PFM delegates all state access

    @property
    def parameters(self) -> ParameterDefaultsByName:
        """Get parameters scoped to this PFM's field_id.

        With flat storage, filters state.parameters to only include fields
        under this PFM's prefix, and strips the prefix from keys.

                Example:
                    state.parameters = {
                        'well_filter_config.well_filter': 2,
                        'well_filter_config.enabled': True,
                        'some_other_field': 'value'
                    }
                    PFM with field_id='well_filter_config' returns:
                    {'well_filter': 2, 'enabled': True}
        """
        return ParameterFormTypeResolver.scoped_parameters(self.state, self.field_id)

    @property
    def parameter_types(self) -> ParameterTypesByName:
        """Derive parameter types from object_instance using UnifiedParameterAnalyzer.

        Single code path for all object types - that's the point of UnifiedParameterAnalyzer.
        Uses self.object_instance (target object for this PFM's scope), NOT self.state.object_instance (root).
        Filters by self.parameters keys (already scoped/stripped for nested PFMs).
        """
        from python_introspect import UnifiedParameterAnalyzer
        param_info_dict = UnifiedParameterAnalyzer.analyze(self.object_instance)
        return ParameterTypesByName(
            (name, info.param_type)
            for name, info in param_info_dict.items()
            if name in self.parameters
        )

    @property
    def param_defaults(self) -> ParameterDefaultsByName:
        """Derive defaults from object_instance (the saved baseline).

        Uses self.object_instance (target object for this PFM's scope), NOT self.state.object_instance (root).
        Uses self.parameters keys (already scoped/stripped for nested PFMs).
        """
        if not is_dataclass(type(self.object_instance)):
            return ParameterDefaultsByName()
        return ParameterDefaultsByName(
            DataclassFieldAccess.raw_items(
                self.object_instance,
                iter(self.parameters.keys()),
            )
        )

    @property
    def _parameter_descriptions(self) -> Dict[str, str]:
        """Delegate to ObjectState._parameter_descriptions."""
        return self.state.parameter_descriptions

    def __init__(self, state: 'ObjectState', config: Optional[FormManagerConfig] = None):
        """
        Initialize PyQt parameter form manager with ObjectState (MODEL).

        PFM is purely VIEW - it receives ObjectState and delegates all MODEL
        concerns to it. ObjectState must be created by the lifecycle owner
        (or looked up from ObjectStateRegistry) before calling PFM.

        Args:
            state: ObjectState instance containing parameters, types, defaults, user_set_fields.
                   Created by lifecycle owner or looked up from ObjectStateRegistry.
            config: Optional configuration object for UI settings
        """
        # Unpack config or use defaults
        config = config or FormManagerConfig()
        global _PFM_SEQ
        _PFM_SEQ += 1
        self._pfm_seq = _PFM_SEQ

        # The state scope owns data and notifications; an explicit config scope owns
        # presentation when a top-level window renders that state in another scope.
        visual_scope_id = (
            config.scope_id if config.scope_id is not None else state.scope_id
        )
        if config.scope_accent_color is None and visual_scope_id is not None:
            try:
                from pyqt_reactive.services.scope_color_service import ScopeColorService
                svc = ScopeColorService.instance()
                accent = svc.get_accent_color(
                    visual_scope_id,
                    step_index=config.scope_step_index,
                )
                if accent is not None:
                    config.scope_accent_color = accent
            except Exception:
                # Be conservative: if service lookup fails, fall back to None
                pass

        # Store field_id EARLY - needed for target_obj navigation
        self.field_id = config.field_id

        # For nested PFMs, navigate to nested object using field_id
        # Root PFM: Use extraction_target (handles __objectstate_delegate__ correctly)
        # Nested PFM: traverse extraction_target using field_id to get nested object
        # CRITICAL: Use _extraction_target for parameter analysis, NOT object_instance
        # object_instance is lifecycle object (e.g., orchestrator), while
        # _extraction_target is editable config object (e.g., PipelineConfig)
        target_obj = state.saved_object
        if self.field_id:
            resolved_target = state.get_resolved_value(self.field_id)
            if resolved_target is not None:
                target_obj = resolved_target
            elif config.function_target is not None:
                target_obj = config.function_target
            else:
                target_obj = FormTargetPathAccess.raw_path(target_obj, self.field_id)

        # Auto-set render_enabled_in_header for nested enableable objects
        # If target_obj is enableable and this is a nested form, render enabled in header
        try:
            from python_introspect import is_enableable
            if config.parent_manager is not None and is_enableable(target_obj):
                config = FormManagerConfig(
                    parent=config.parent,
                    context_obj=config.context_obj,
                    exclude_params=config.exclude_params,
                    initial_values=config.initial_values,
                    parent_manager=config.parent_manager,
                    read_only=config.read_only,
                    scope_id=config.scope_id,
                    color_scheme=config.color_scheme,
                    use_scroll_area=config.use_scroll_area,
                    state=config.state,
                    field_id=config.field_id,
                    render_enabled_in_header=True,
                    scope_accent_color=config.scope_accent_color,
                    scope_step_index=config.scope_step_index,
                    function_target=config.function_target,
                )
        except ImportError:
            pass

        # Keep canonical dotted `field_id` for scoping/identity; store the target
        # type name separately for logging/diagnostics.
        target_type_name = type(target_obj).__name__

        with timer(f"ParameterFormManager.__init__ ({target_type_name})", threshold_ms=5.0):
            QWidget.__init__(self, config.parent)

            # Store ObjectState reference - PFM delegates MODEL to state
            self.state = state
            self._form_widget: Optional[QWidget] = None
            self._extra_repaint_callbacks: List[Callable[[], None]] = []

            # Store target object for this PFM's scope (root or nested)
            # CRITICAL: Nested PFMs need their own object_instance for type conversions, etc.
            self.object_instance = target_obj
            self._target_type_name = target_type_name
            self.context_obj = state.context_obj
            self.scope_id = state.scope_id
            self.read_only = config.read_only
            self._parent_manager = config.parent_manager
            self.render_enabled_in_header = config.render_enabled_in_header
            self._scope_accent_color = config.scope_accent_color  # Store for widget creation
            self._scope_step_index = config.scope_step_index
            self._visual_scope_id = visual_scope_id

            # Store full scope color scheme for nested GroupBox borders/backgrounds
            self._scope_color_scheme = None
            if self._visual_scope_id is not None:
                from pyqt_reactive.services.scope_color_service import ScopeColorService
                self._scope_color_scheme = ScopeColorService.instance().get_color_scheme(
                    self._visual_scope_id,
                    step_index=config.scope_step_index,
                )

            logger.debug(
                "[PFM_INIT] seq=%s field_id=%s target=%s is_nested=%s parent_cls=%s scope_id=%s",
                self._pfm_seq,
                self.field_id,
                self._target_type_name,
                self._parent_manager is not None,
                type(self._parent_manager).__name__ if self._parent_manager is not None else None,
                self.scope_id,
            )

            # Track completion callbacks for async widget creation
            self._on_build_complete_callbacks = []
            self._on_placeholder_refresh_complete_callbacks = []

            # STEP 1: State data is accessed via self.state (no copying)
            # Properties delegate to ObjectState - single source of truth

            # STEP 2: Build UI config (still needed for widget creation)
            with timer("  Build config", threshold_ms=5.0):
                from pyqt_reactive.forms.parameter_form_service import ParameterFormService
                from pyqt_reactive.forms.form_init_service import (
                    ExtractedParameters, ConfigBuilderService
                )

                self.service = ParameterFormService()
                # Use the canonical dotted-path `field_id`. For nested PFMs a
                # non-empty `field_id` is required; root PFMs may use an empty
                # `field_id` to indicate top-level scope.
                if not config.field_id and config.parent_manager is not None:
                    raise ValueError(
                        "ParameterFormManager requires a canonical dotted `field_id` in FormManagerConfig for nested forms;"
                        " do not rely on derived type names as a fallback"
                    )
                from python_introspect import UnifiedParameterAnalyzer

                param_info_dict = UnifiedParameterAnalyzer.analyze(target_obj, exclude_params=config.exclude_params)
                scoped_parameters = ParameterFormTypeResolver.scoped_parameters(state, self.field_id)
                derived_param_types = {
                    name: ParameterFormTypeResolver.field_type(self, name, info.param_type)
                    for name, info in param_info_dict.items()
                    if name in scoped_parameters
                }

                # Include enabled field in normal processing (will be moved to title later)
                default_value = scoped_parameters
                param_type = derived_param_types

                # Access state data directly - ObjectState is single source of truth
                # Pass scoped parameters and target object for nested PFMs
                extracted = ExtractedParameters(
                    default_value=default_value,  # Use scoped parameters (filtered/stripped)
                    param_type=param_type,
                    # Provide descriptions as a dotted-path dict (optionally deferred)
                    # so downstream lookup is simple and collision-free.
                    description=lambda: state.parameter_descriptions,
                    object_instance=target_obj,  # Use nested object for nested PFMs
                )
                form_config = ConfigBuilderService.build(
                    self.field_id, extracted, state.context_obj, config.color_scheme, config.parent_manager, self.service, config
                )
                # METAPROGRAMMING: Auto-unpack all fields to self
                ValueCollectionService.unpack_to_self(self, form_config)

            # STEP 3: Initialize VIEW-only attributes
            self.widgets, self.reset_buttons, self.nested_managers = {}, {}, {}
            self.labels = {}  # Track LabelWithHelp widgets for bold styling
            self._field_flash_targets: Dict[str, "StructuralFlashTarget"] = {}
            self._pending_nested_managers: Dict[str, 'ParameterFormManager'] = {}
            self.form_tree = ParameterFormTreeIndex(self)
            self.chrome_sync = ParameterFormChromeSync(self)

            # STEP 4: VIEW-only flags (state tracking is in ObjectState)
            self._initial_load_complete, self._block_cross_window_updates, self._in_reset = False, False, False
            self._dispatching = False
            self._cross_window_refresh_timer: Optional[QTimer] = None
            self.shared_reset_fields = set()  # VIEW-only: tracks field paths for cross-window reset styling
            self._locally_applied_model_paths: Set[str] = set()

            # CROSS-WINDOW: Connect to change notifications (only root managers)
            # Nested managers are internal to their window and should not participate in cross-window updates.
            # Root forms subscribe to their ObjectState's path-scoped resolved-change signal below; the
            # registry-wide listener remains for non-form preview/list consumers that do not own an ObjectState.
            if self._parent_manager is None:
                from objectstate import ObjectStateRegistry
                # Invalidate cache so newly opened windows build fresh snapshots
                ObjectStateRegistry.increment_token(notify=False)
            
            # Register hierarchy relationship for cross-window placeholder resolution
            if self.context_obj is not None and not self._parent_manager:
                register_hierarchy_relationship(type(self.context_obj), type(self.object_instance))
            elif self._parent_manager is not None and self._parent_manager.object_instance and self.object_instance:
                # Nested manager: register relationship from parent to this nested object
                # Needed so is_ancestor_in_context recognizes parent → child when filtering live context
                register_hierarchy_relationship(type(self._parent_manager.object_instance), type(self.object_instance))

            # Store backward compatibility attributes
            self.parameter_info = self.config.parameter_info
            self.use_scroll_area = self.config.use_scroll_area
            self.function_target = self.config.function_target
            self.color_scheme = self.config.color_scheme

            # STEP 5: Initialize services (metaprogrammed service + auto-unpack)
            with timer("  Initialize services", threshold_ms=1.0):
                from pyqt_reactive.forms.form_init_service import ServiceFactoryService
                services = ServiceFactoryService.build()
                # METAPROGRAMMING: Auto-unpack all services to self with _ prefix
                ValueCollectionService.unpack_to_self(self, services, prefix="_")

            # Get widget creator from the concrete PyQt strategy.
            self._widget_creator = create_pyqt6_widget

            # ANTI-DUCK-TYPING: Initialize ABC-based widget operations
            self._widget_ops = WidgetOperations()
            self._context_event_coordinator = None
            self._pending_path_scoped_state_refresh: set[str] | None = None
            self._pending_resolved_changed_paths: Set[str] = set()
            self._resolved_changed_flush_scheduled = False

            # GAME ENGINE: Initialize flash overlay state BEFORE building widgets
            # (widgets call register_flash_groupbox during build_form)
            if self._parent_manager is None:
                self._init_visual_update_mixin()

            # STEP 6: Set up UI
            with timer("  Setup UI (widget creation)", threshold_ms=10.0):
                self.setup_ui()

            # STEP 7: Connect signals (explicit service)
            with timer("  Connect signals", threshold_ms=1.0):
                SignalService.connect_all_signals(self)

                # NOTE: Cross-window registration now handled by CALLER using:
                #   with SignalService.cross_window_registration(manager):
                #       dialog.exec()
                # For backward compatibility during migration, we still register here
                # TODO: Remove this after all callers are updated to use context manager
                SignalService.register_cross_window_signals(self)

            # Flash animation: Subscribe to resolved value changes (root only)
            # NOTE: _init_visual_update_mixin() is called earlier (before setup_ui)
            if self._parent_manager is None:
                self.state.on_resolved_changed(self._on_resolved_values_changed)
                logger.debug(f"🔔 CALLBACK_LEAK_DEBUG: Registered callback for {self.field_id} (PFM id={id(self)}), "
                           f"total callbacks on ObjectState: {len(self.state._on_resolved_changed_callbacks)}, "
                           f"scope_id={self.state.scope_id}")

            # Materialized state changes: Subscribe once (root only)
            if self._parent_manager is None:
                self.state.on_state_changed(self._on_materialized_state_changed)

            # STEP 8: _user_set_fields starts empty and is populated only when user edits widgets
            # (via _emit_parameter_change). Do NOT populate during initialization, as that would
            # include inherited values that weren't explicitly set by the user.

            # STEP 9: Mark initial load as complete
            is_nested = self._parent_manager is not None
            self._initial_load_complete = True
            if not is_nested:
                self._apply_to_nested_managers(
                    lambda name, manager: manager.mark_initial_load_complete()
                )

            # STEP 10: Initial refresh - REMOVED (now done in _execute_post_build_sequence)
            # The FormBuildOrchestrator already does ONE cascading refresh at the end of
            # widget building. Calling InitialRefreshStrategy.execute here was redundant
            # and caused every manager to be refreshed TWICE during init.
            pass

    # ==================== WIDGET CREATION METHODS ====================

    def mark_initial_load_complete(self) -> None:
        """Mark this form as fully initialized after root build completion."""
        self._initial_load_complete = True

    def schedule_lifecycle_callback(
        self,
        delay_ms: int,
        callback: Callable[[], None],
    ) -> QTimer:
        """Schedule callback work owned by this manager's QObject lifetime.

        A static ``QTimer.singleShot`` retains its Python callable after this
        widget's C++ object is deleted. Parenting the one-shot timer to the form
        manager lets Qt cancel that work during destruction before the callback
        can enter stale child widgets or flash factories.
        """
        timer = QTimer(self)
        timer.setSingleShot(True)

        def run_callback() -> None:
            timer.deleteLater()
            callback()

        timer.timeout.connect(run_callback)
        timer.start(delay_ms)
        return timer

    def setup_ui(self):
        """Set up the UI layout."""
        # timer decorator made optional

        is_nested = self._parent_manager is not None

        with timer("    Layout setup", threshold_ms=1.0):
            layout = QVBoxLayout(self)
            layout.setSpacing(CURRENT_LAYOUT.main_layout_spacing)
            layout.setContentsMargins(*CURRENT_LAYOUT.main_layout_margins)

        # Always apply styling
        with timer("    Style generation", threshold_ms=1.0):
            from pyqt_reactive.theming.style_generator import StyleSheetGenerator
            style_gen = StyleSheetGenerator(self.color_scheme)
            self.setStyleSheet(style_gen.generate_config_window_style())

        # Build form content
        with timer("    Build form", threshold_ms=5.0):
            form_widget = self.build_form()

        # OPTIMIZATION: Never add scroll areas for nested configs
        # This saves ~2ms per nested config × 20 configs = 40ms
        with timer("    Add scroll area", threshold_ms=1.0):
            if self.config.use_scroll_area and not is_nested:
                scroll_area = QScrollArea()
                scroll_area.setWidgetResizable(True)
                scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                scroll_area.setWidget(form_widget)
                layout.addWidget(scroll_area)
            else:
                layout.addWidget(form_widget)

    def build_form(self) -> QWidget:
        """Build form UI using orchestrator service."""
        # timer decorator made optional

        if self._form_widget is not None:
            logger.debug(
                "[PFM_BUILD_FORM] seq=%s field_id=%s reuse_existing_form_widget",
                self._pfm_seq,
                self.field_id,
            )
            return self._form_widget

        logger.debug(
            "[PFM_BUILD_FORM] seq=%s field_id=%s param_count=%s",
            self._pfm_seq,
            self.field_id,
            len(self.form_structure.parameters),
        )
        with timer("      Create content widget", threshold_ms=1.0):
            content_widget = QWidget()
            content_layout = QVBoxLayout(content_widget)
            content_layout.setSpacing(CURRENT_LAYOUT.content_layout_spacing)
            content_layout.setContentsMargins(*CURRENT_LAYOUT.content_layout_margins)

        # PHASE 2A: Use orchestrator to eliminate async/sync duplication
        orchestrator = FormBuildOrchestrator()
        use_async = orchestrator.should_use_async(len(self.form_structure.parameters))
        logger.debug(
            "[PFM_BUILD_WIDGETS] seq=%s field_id=%s use_async=%s",
            self._pfm_seq,
            self.field_id,
            use_async,
        )
        orchestrator.build_widgets(self, content_layout, self.form_structure.parameters, use_async)

        self._form_widget = content_widget
        return content_widget

    def _create_widget_for_param(self, param_info: ParameterInfo) -> QWidget:
        """Create widget for a parameter. Type auto-detected from param_info."""
        from pyqt_reactive.forms.widget_creation_config import WidgetCreationPipeline
        logger.debug(
            "[PFM_CREATE_PARAM] seq=%s field_id=%s param=%s widget_creation_type=%s",
            self._pfm_seq,
            self.field_id,
            param_info.name,
            param_info.widget_creation_type,
        )
        return WidgetCreationPipeline(self, param_info).run()

    def _create_widgets_async(self, layout, param_infos, on_complete=None, on_batch_complete=None):
        """Create widgets asynchronously to avoid blocking the UI.

        Args:
            layout: Layout to add widgets to
            param_infos: List of parameter info objects
            on_complete: Optional callback to run when all widgets are created
            on_batch_complete: Optional callback to run after each batch (receives list of widgets)
        """
        logger.debug(
            "[ASYNC_CREATE] seq=%s field_id=%s param_count=%s",
            self._pfm_seq,
            self.field_id,
            len(param_infos),
        )
        # Create widgets in batches using QTimer to yield to event loop
        batch_size = 3  # Create 3 widgets at a time
        index = 0
        batch_timer = QTimer(self)
        batch_timer.setSingleShot(True)

        def create_next_batch():
            nonlocal index

            batch_start = index
            batch_end = min(index + batch_size, len(param_infos))
            logger.debug(
                "[ASYNC_CREATE] seq=%s field_id=%s batch=%s-%s of %s",
                self._pfm_seq,
                self.field_id,
                batch_start,
                batch_end,
                len(param_infos),
            )

            # Guard: Check if layout's parent widget was deleted (window closed during async build)
            try:
                parent = layout.parentWidget()
                if parent is None:
                    logger.warning("Async widget creation aborted: layout parent is None")
                    return
            except RuntimeError:
                # Layout itself was deleted
                logger.warning("Async widget creation aborted: layout was deleted")
                return

            batch_widgets = []

            for i in range(index, batch_end):
                param_info = param_infos[i]
                widget = self._create_widget_for_param(param_info)
                try:
                    layout.addWidget(widget)
                    batch_widgets.append((param_info.name, widget))
                except RuntimeError as e:
                    logger.warning(f"Async widget creation aborted during addWidget: {e}")
                    return

            index = batch_end

            # Apply styling to this batch immediately
            logger.debug(f"[ASYNC_CREATE] Batch complete: field_id={self.field_id}, batch_widgets={len(batch_widgets)}, on_batch_complete={'set' if on_batch_complete else None}")
            if on_batch_complete and batch_widgets:
                try:
                    on_batch_complete(batch_widgets)
                except Exception as e:
                    logger.warning(f"Error in batch completion callback: {e}")

            # Schedule next batch if there are more widgets
            if index < len(param_infos):
                batch_timer.start(0)
                return

            batch_timer.deleteLater()
            if on_complete:
                logger.debug(
                    "[ASYNC_CREATE] All widgets created for %s, running "
                    "on_complete callback",
                    self.field_id,
                )
                on_complete()

        # Start creating widgets
        batch_timer.timeout.connect(create_next_batch)
        batch_timer.start(0)

    def _create_nested_form_inline(
        self,
        param_name: str,
        unwrapped_type: type | None = None,
        current_value=None,
    ) -> 'ParameterFormManager':
        """Create nested PFM that shares root ObjectState with different field_id.

        With flat storage, nested PFMs share the same ObjectState instance as the parent,
        but use a different field_id to scope their access.

        Args:
            param_name: Name of the nested parameter (becomes part of field_id)
            unwrapped_type: Ignored (kept for ABC compatibility)
            current_value: Ignored (kept for ABC compatibility)
        """
        # Build nested field id (dotted path)
        nested_id = f'{self.field_id}.{param_name}' if self.field_id else param_name

        # Create nested PFM (VIEW) that shares the same ObjectState (MODEL)
        nested_config = FormManagerConfig(
            parent=self,
            parent_manager=self,
            color_scheme=self.config.color_scheme,
            field_id=nested_id,  # Scope access to nested fields
            scope_id=self._visual_scope_id,
            scope_accent_color=self._scope_accent_color,  # Inherit scope accent color
            scope_step_index=self._scope_step_index,  # Preserve step index for scope styling
            function_target=unwrapped_type,
        )
        nested_manager = ParameterFormManager(
            state=self.state,  # CRITICAL: Share the same ObjectState instance
            config=nested_config
        )
        logger.debug(
            "[PFM_NESTED_CREATE] parent_seq=%s parent_field_id=%s param=%s nested_seq=%s nested_field_id=%s",
            self._pfm_seq,
            self.field_id,
            param_name,
            nested_manager._pfm_seq,
            nested_manager.field_id,
        )

        # Inherit lazy/global editing context from parent
        try:
            nested_manager.config.is_lazy_dataclass = self.config.is_lazy_dataclass
            nested_manager.config.is_global_config_editing = self.config.is_global_config_editing
        except Exception:
            pass

        # Store nested manager
        self.nested_managers[param_name] = nested_manager

        # Register with root manager for async completion tracking
        # Count parameters with nested id
        nested_path = DottedFieldPath(nested_id)
        param_count = sum(
            1
            for path in self.state.parameters.keys()
            if path != nested_id and nested_path.contains_path(path)
        )
        root_manager = self
        while root_manager._parent_manager is not None:
            root_manager = root_manager._parent_manager

        if self.should_use_async(param_count):
            unique_key = f"{self.field_id}.{param_name}"
            root_manager._pending_nested_managers[unique_key] = nested_manager

        return nested_manager

    def _convert_widget_value(self, value: WidgetValue, param_name: str) -> ParameterValue:
        """
        Convert widget value to proper type.

        Applies both PyQt-specific conversions (Path, tuple/list parsing) and
        service layer conversions (enums, basic types, Union handling).
        """
        from pyqt_reactive.forms.widget_strategies import convert_widget_value_to_type

        param_type = self.parameter_types.get(param_name, type(value))

        # PyQt-specific type conversions first
        converted_value = convert_widget_value_to_type(value, param_type)

        # Then apply service layer conversion (enums, basic types, Union handling, etc.)
        converted_value = self.service.convert_value_to_type(converted_value, param_type, param_name, type(self.object_instance))

        return converted_value

    def reset_all_parameters(self) -> None:
        """Reset all parameters - just call reset_parameter for each parameter."""
        # timer decorator made optional

        with timer(f"reset_all_parameters ({self.field_id})", threshold_ms=50.0):
            # PHASE 2A: Use FlagContextManager instead of manual flag management
            # This guarantees flags are restored even on exception
            with FlagContextManager.reset_context(self, block_cross_window=True):
                # CRITICAL: Iterate over form_structure.parameters instead of self.parameters
                # form_structure only contains visible (non-hidden) parameters,
                # while self.parameters may include ui_hidden parameters that don't have widgets
                param_names = [param_info.name for param_info in self.form_structure.parameters]
                for param_name in param_names:
                    # Call reset_parameter directly to avoid nested context managers
                    self.reset_parameter(param_name)

            # OPTIMIZATION: Single placeholder refresh at the end instead of per-parameter
            # This is much faster than refreshing after each reset
            # CRITICAL: Use refresh_with_live_context to build context stack from tree registry
            # Even when resetting to defaults, we need live context for sibling inheritance
            # REFACTORING: Inline delegate calls
            self._parameter_ops_service.refresh_with_live_context(self)

            # Update all reset buttons and provenance button once at the end
            for param_name in param_names:
                self._update_reset_button_styling(param_name)
            self.chrome_sync.update_provenance_button_visibility()

            # CRITICAL: Update groupbox dirty markers AFTER all resets are complete
            # Individual reset_parameter calls update during the loop, but we need
            # a final update to reflect the complete reset state
            self.chrome_sync.update_owning_groupbox_dirty_marker()

    def update_parameter(self, param_name: str, value: ParameterValue) -> None:
        """Update parameter value using shared service layer.

        With flat storage, prepends field_id to create full dotted path.
        """
        if param_name not in self.parameters:
            return

        # Convert value using service layer
        converted_value = self.service.convert_value_to_type(
            value, self.parameter_types.get(param_name, type(value)), param_name, type(self.object_instance)
        )

        # Update corresponding widget if it exists
        # ANTI-DUCK-TYPING: Skip widget update for nested containers (they don't implement ValueSettable)
        if param_name in self.widgets:
            widget = self.widgets[param_name]
            from pyqt_reactive.protocols.widget_protocols import (
                RawResolvedValueSettable,
                ValueSettable,
            )
            if isinstance(widget, ValueSettable) and not isinstance(
                widget,
                RawResolvedValueSettable,
            ):
                self._widget_service.update_widget_value(widget, converted_value, param_name, False, self)

        # ATOMIC: If this state has a parent, wrap in atomic so forwarded parent
        # updates remain one undo step while preserving this state's scope as the
        # semantic edit owner.
        has_parent = self.state._parent_state is not None
        logger.debug(f"[ATOMIC_CHECK] field_id={self.field_id}, has_parent={has_parent}, state={self.state}")
        if has_parent:
            from objectstate import ObjectStateRegistry
            logger.debug(f"[ATOMIC_CHECK] Entering atomic block for {param_name}")
            with ObjectStateRegistry.atomic("edit parameter", scope_id=self.scope_id):
                # Route through dispatcher for consistent behavior (sibling refresh, cross-window, etc.)
                # This is INSIDE the atomic block so parent step updates are also coalesced
                event = FieldChangeEvent(param_name, converted_value, self)
                FieldChangeDispatcher.instance().dispatch(event)
            logger.debug(f"[ATOMIC_CHECK] Exited atomic block for {param_name}")
        else:
            # Route through dispatcher for consistent behavior (sibling refresh, cross-window, etc.)
            event = FieldChangeEvent(param_name, converted_value, self)
            FieldChangeDispatcher.instance().dispatch(event)

    def reset_parameter(self, param_name: str) -> None:
        """Reset parameter to signature default.

        With flat storage, prepends field_id to create full dotted path.
        """
        if param_name not in self.parameters:
            return

        # Build full dotted path for state update
        dotted_path = f'{self.field_id}.{param_name}' if self.field_id else param_name

        with FlagContextManager.reset_context(self, block_cross_window=False):
            self._parameter_ops_service.reset_parameter(self, param_name)

        self.chrome_sync.dispatch_reset(param_name)

        # Update label styling after reset
        self.chrome_sync.update_label_styling(param_name)
        
        # Update reset button styling
        self._update_reset_button_styling(param_name)
        
        # Update provenance button visibility
        self.chrome_sync.update_provenance_button_visibility()

    def _update_reset_button_styling(self, param_name: str) -> None:
        """Update reset button styling: * and _ indicators."""
        if param_name not in self.reset_buttons:
            return
        
        from pyqt_reactive.utils.styling_utils import update_reset_button_styling
        reset_button = self.reset_buttons[param_name]
        update_reset_button_styling(reset_button, self.state, self.field_id, param_name)

    def queue_field_flash(self, full_path: str) -> None:
        """Queue flash feedback for a changed field path."""
        flash_trace(
            "form.queue_field_flash",
            manager=self.field_id,
            root=self.form_tree.root().field_id,
            path=full_path,
        )
        self.form_tree.root()._queue_leaf_flash_for_path(full_path)

    def flash_scope_id(self) -> str | None:
        """Return this form's ObjectState scope for local flash isolation."""
        return self.scope_id

    def sync_after_model_field_change(
        self,
        param_name: str,
        full_path: str,
        *,
        queue_flash: bool = True,
        changed_paths: Set[str] | None = None,
    ) -> None:
        """Synchronize visible field chrome after ObjectState accepts a change."""
        refreshed_compound_owner_paths: set[str] = set()
        if changed_paths:
            refreshed_compound_owner_paths = (
                self.chrome_sync.refresh_widgets_for_paths(changed_paths)
                or set()
            )
        self._locally_applied_model_paths.add(full_path)
        self.chrome_sync.after_model_field_change(
            param_name,
            full_path,
            queue_flash=queue_flash,
            changed_paths=changed_paths,
            refreshed_compound_owner_paths=refreshed_compound_owner_paths,
        )

    def sync_enabled_field_visuals(self, value: ParameterValue) -> None:
        """Synchronize enabled-field dependent styling after an enabled change."""
        self.chrome_sync.enabled_field_visuals(value)

    def register_field_flash_target(
        self,
        field_name: str,
        target: "StructuralFlashTarget",
    ) -> None:
        """Register a field-owned structural flash target."""

        self._field_flash_targets[field_name] = target

    def field_flash_target(self, field_name: str) -> "StructuralFlashTarget | None":
        """Return a field-owned structural flash target, if one was declared."""

        return self._field_flash_targets.get(field_name)

    def update_groupbox_dirty_markers(self, dirty_prefixes: set, sig_diff_prefixes: set = None) -> None:
        """Update groupbox titles with dirty markers and signature diff underline.

        Called by ConfigHierarchyTreeHelper.update_dirty_styling() so tree items
        and groupbox titles use the SAME prefixes computed ONCE.

        Args:
            dirty_prefixes: Pre-computed set of dirty paths and their ancestors (for asterisk)
            sig_diff_prefixes: Pre-computed set of signature diff paths and ancestors (for underline)
        """
        if sig_diff_prefixes is None:
            sig_diff_prefixes = set()
        self.chrome_sync.update_groupbox_dirty_markers(dirty_prefixes, sig_diff_prefixes)

    # DELETED: MODEL DELEGATION - callers use self.state.get_*() directly
    # DELETED: _on_nested_parameter_changed - replaced by FieldChangeDispatcher

    def _apply_to_nested_managers(self, callback: Callable[[str, 'ParameterFormManager'], None]) -> None:
        """Apply operation to all nested managers."""
        for param_name, nested_manager in self.nested_managers.items():
            callback(param_name, nested_manager)

    def _on_nested_manager_complete(self, nested_manager) -> None:
        """
        Called by nested managers when they complete async widget creation.

        ANTI-DUCK-TYPING: _pending_nested_managers always exists (set in __init__).
        """
        # Find and remove this manager from pending dict
        key_to_remove = None
        for key, manager in self._pending_nested_managers.items():
            if manager is nested_manager:
                key_to_remove = key
                break

        if key_to_remove:
            del self._pending_nested_managers[key_to_remove]

        # If all nested managers are done, delegate to orchestrator
        if len(self._pending_nested_managers) == 0:
            # PHASE 2A: Use orchestrator for post-build sequence
            orchestrator = FormBuildOrchestrator()
            orchestrator._execute_post_build_sequence(self)

    # ==================== CROSS-WINDOW CONTEXT UPDATE METHODS ====================

    # DELETED: _emit_cross_window_change - moved to FieldChangeDispatcher
    # DELETED: _update_thread_local_global_config - moved to ObjectState

    def _on_live_context_changed(self):
        """Handle notification that live context changed (another form edited a value).

        Schedule a placeholder refresh so this form shows updated inherited values.
        Uses emit_signal=False to prevent infinite ping-pong between forms.
        """
        # Skip if this form triggered the change
        if self._block_cross_window_updates:
            return

        logger.debug(
            "[CROSS-WINDOW] %s: scheduling debounced placeholder refresh",
            self.field_id,
        )
        self.queue_visual_update()
        self._schedule_cross_window_placeholder_refresh()

    def _schedule_cross_window_placeholder_refresh(self) -> None:
        """Debounce inherited placeholder refreshes after cross-window edits."""
        timer = self._cross_window_refresh_timer
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._refresh_cross_window_placeholders)
            self._cross_window_refresh_timer = timer

        timer.start(self.CROSS_WINDOW_PLACEHOLDER_REFRESH_MS)

    def _refresh_cross_window_placeholders(self) -> None:
        """Refresh placeholder text for fields still inheriting from context."""
        if self._block_cross_window_updates:
            return

        self._parameter_ops_service.refresh_with_live_context(self)
        self.queue_visual_update()

    def unregister_from_cross_window_updates(self):
        """Unregister from cross-window updates."""
        try:
            from objectstate import ObjectStateRegistry
            ObjectStateRegistry.disconnect_listener(self._on_live_context_changed)

            # CRITICAL: Unregister resolved value change callback to prevent memory leak
            # Without this, closed windows leave callbacks in ObjectState that fire on every change
            if self._parent_manager is None:
                callbacks_before = len(self.state._on_resolved_changed_callbacks)
                self.state.off_resolved_changed(self._on_resolved_values_changed)
                callbacks_after = len(self.state._on_resolved_changed_callbacks)
                logger.debug(f"🔔 CALLBACK_LEAK_DEBUG: Unregistered callback for {self.field_id}, "
                           f"callbacks: {callbacks_before} -> {callbacks_after}")

            # Unregister state change callback (root only)
            if self._parent_manager is None:
                self.state.off_state_changed(self._on_materialized_state_changed)

            if self.context_obj is not None and not self._parent_manager:
                unregister_hierarchy_relationship(type(self.object_instance))
            # Invalidate cache + notify listeners that a form closed
            ObjectStateRegistry.increment_token()
        except Exception as e:
            logger.warning(f"Unregister error: {e}")

    def refresh_widgets_from_state(self):
        """Refresh all widget values from state.parameters.

        Called during time-travel to sync Qt widgets with restored ObjectState.
        """
        self.chrome_sync.refresh_widgets_from_state()

    def _on_materialized_state_changed(self, changed_paths: Set[str]) -> None:
        """Refresh dirty/signature chrome after materialized ObjectState changes."""
        if self._parent_manager is not None:
            return
        if changed_paths:
            if self._resolved_changed_flush_scheduled:
                if self._pending_path_scoped_state_refresh is None:
                    self._pending_path_scoped_state_refresh = set()
                self._pending_path_scoped_state_refresh.update(changed_paths)
                return
            self.chrome_sync.state_changed_for_paths(changed_paths)
            return
        self.chrome_sync.state_changed()

    # ==================== GROUPBOX FLASH ANIMATION (FlashMixin) ====================

    def _on_resolved_values_changed(self, changed_paths: Set[str]):
        """Handle resolved value changes - queue flashes AND refresh placeholders.

        SCOPE-AWARE: This callback is fired by THIS window's ObjectState, so we only
        flash THIS window's elements, not ALL windows globally.

        LEAF FLASH: For each changed path, we use INVERSE masking - flash the groupbox
        INCLUDING all sibling fields, but mask out the specific changed widget.
        This highlights "all fields that inherited the change".

        TIME-TRAVEL: When _in_time_travel flag is set, also refresh widget values
        for the changed paths (since user didn't type - we need to sync widgets).
        """
        if self._parent_manager is not None:
            return  # Only root manager handles this

        self._pending_resolved_changed_paths.update(changed_paths)
        if self._resolved_changed_flush_scheduled:
            return
        self._resolved_changed_flush_scheduled = True
        QTimer.singleShot(0, self._flush_resolved_values_changed)

    def _flush_resolved_values_changed(self) -> None:
        """Flush coalesced resolved-value UI refresh for one root manager."""
        if self._parent_manager is not None:
            return
        changed_paths = set(self._pending_resolved_changed_paths)
        self._pending_resolved_changed_paths.clear()
        self._resolved_changed_flush_scheduled = False
        if not changed_paths:
            return
        local_paths = set(self._locally_applied_model_paths)
        self._locally_applied_model_paths.clear()
        widget_refresh_paths = self._widget_refresh_paths_for_changed_paths(
            changed_paths,
            local_paths,
        )
        deferred_state_refresh_paths = self._pending_path_scoped_state_refresh or set()
        state_refresh_paths = changed_paths | deferred_state_refresh_paths

        from objectstate import ObjectStateRegistry
        from objectstate.time_travel_profile import TimeTravelProfiler

        logger.debug(f"🔔 CALLBACK_LEAK_DEBUG: _on_resolved_values_changed invoked for {self.field_id}, "
                   f"changed_paths={changed_paths}")
        logger.debug(f"[FLASH] _on_resolved_values_changed: {changed_paths}")

        # Refresh widget display from the same canonical ObjectState paths that
        # drive flash/styling. Local form edits have already set the same value;
        # external ObjectState mutations (MCP, restore, time travel) need this
        # listener to pull the visible widget values from ObjectState.
        with TimeTravelProfiler.phase(
            "pyqt.form.refresh_widgets_for_paths",
            scope=self.state.scope_id,
            paths=len(changed_paths),
        ):
            refreshed_compound_owner_paths: set[str] = set()
            if widget_refresh_paths:
                refreshed_compound_owner_paths.update(
                    self.chrome_sync.refresh_widgets_for_paths(widget_refresh_paths)
                    or set()
                )
            if state_refresh_paths:
                self.chrome_sync.state_changed_for_paths(
                    state_refresh_paths,
                    refreshed_compound_owner_paths,
                )
            self._pending_path_scoped_state_refresh = None

        if ObjectStateRegistry._in_time_travel:
            # CRITICAL: Refresh enabled styling for all managers after time-travel
            # Widget updates bypass the FieldChangeDispatcher (signals blocked), so styling
            # isn't triggered automatically. We must manually sync styling to match restored state.
            with TimeTravelProfiler.phase(
                "pyqt.form.refresh_enabled_styling",
                scope=self.state.scope_id,
            ):
                self._apply_to_nested_managers(
                    lambda _, manager: manager._enabled_field_styling_service.refresh_enabled_styling(manager)
                )

        # For each changed path, register and queue a LEAF flash
        with TimeTravelProfiler.phase(
            "pyqt.form.queue_flash_paths",
            scope=self.state.scope_id,
            paths=len(changed_paths),
        ):
            flash_paths: list[str] = []
            for path in ParameterFormManager._flash_paths_for_changed_paths(changed_paths):
                if self.field_id:
                    if '.' in path:
                        path_prefix = path.rsplit('.', 1)[0]
                        if path_prefix != self.field_id:
                            continue
                    else:
                        continue
                queued_path = self._queue_leaf_flash_for_path(
                    path,
                    queue_flash=False,
                )
                if queued_path is not None:
                    flash_paths.append(queued_path)
            self.queue_flash_local_batch(flash_paths)

        if changed_paths:
            sample_path = next(iter(changed_paths))
            sample_leaf = sample_path.split('.')[-1] if '.' in sample_path else sample_path
            sample_prefix = sample_path.rsplit('.', 1)[0] if '.' in sample_path else None
            logger.debug(f"[FLASH TRAIL] prefix={sample_prefix}, leaf_field={sample_leaf}")

    @classmethod
    def _exclude_local_edit_paths(
        cls,
        changed_paths: Set[str],
        local_paths: Set[str],
    ) -> Set[str]:
        """Return changed paths that were not just applied by this form."""
        if not local_paths:
            return set(changed_paths)
        return {
            changed_path
            for changed_path in changed_paths
            if not any(
                DottedFieldPath(local_path).contains_path(changed_path)
                for local_path in local_paths
            )
        }

    def _widget_refresh_paths_for_changed_paths(
        self,
        changed_paths: Set[str],
        local_paths: Set[str],
    ) -> Set[str]:
        """Return changed paths whose visible widget value must be pulled from ObjectState."""

        if not local_paths:
            return set(changed_paths)

        return {
            changed_path
            for changed_path in changed_paths
            if (
                not any(
                    DottedFieldPath(local_path).contains_path(changed_path)
                    for local_path in local_paths
                )
                or self._path_needs_resolved_preview_refresh(changed_path)
            )
        }

    def _path_needs_resolved_preview_refresh(self, path: str) -> bool:
        """Return whether a raw ``None`` path needs its inherited preview repainted."""

        missing = object()
        raw_value = self.state.parameters.get(path, missing)
        if raw_value is not None:
            return False
        return self.state.get_resolved_value(path) is not None

    @staticmethod
    def _flash_paths_for_changed_paths(changed_paths: Set[str]) -> tuple[str, ...]:
        """Return the most specific visual paths from an ObjectState change set."""

        from objectstate import StructuralFieldPath

        structural_groups: dict[str, list[str]] = {}
        nonstructural_paths: list[str] = []
        for path in sorted(changed_paths):
            structural_path = StructuralFieldPath.from_display_path(path)
            if structural_path is None:
                nonstructural_paths.append(path)
                continue
            structural_groups.setdefault(
                structural_path.owner_field_path.value,
                [],
            ).append(path)

        selected_paths: set[str] = set()
        suppressed_paths: set[str] = set()
        for owner_path, leaf_paths in structural_groups.items():
            if len(leaf_paths) == 1:
                selected_paths.add(leaf_paths[0])
                suppressed_paths.add(owner_path)
                continue
            selected_paths.add(owner_path)
            suppressed_paths.update(leaf_paths)

        for path in nonstructural_paths:
            if path in suppressed_paths:
                continue
            path_owner = DottedFieldPath(path)
            if any(
                other != path
                and path_owner.contains_path(other)
                for other in selected_paths
            ):
                continue
            selected_paths.add(path)
        return tuple(sorted(selected_paths))

    def _queue_leaf_flash_for_path(
        self,
        path: str,
        *,
        queue_flash: bool = True,
    ) -> str | None:
        """Queue a leaf flash for a changed path.

        Finds the groupbox, leaf widget, and its label, registers a leaf flash element
        (which masks title + leaf_widget + label_widget), and queues the flash animation.
        """
        if self._parent_manager is not None:
            flash_trace(
                "form.leaf_flash.delegate_to_root",
                manager=self.field_id,
                root=self.form_tree.root().field_id,
                path=path,
            )
            return self.form_tree.root()._queue_leaf_flash_for_path(
                path,
                queue_flash=queue_flash,
            )

        flash_trace("form.leaf_flash.start", manager=self.field_id, path=path)
        logger.debug("[FLASH TRAIL] _queue_leaf_flash_for_path START: path=%s", path)
        if self._queue_structural_flash_for_object_state_path(
            path,
            queue_flash=queue_flash,
        ):
            return path

        # Find the prefix (groupbox) and leaf field name
        prefix = self.form_tree.matching_prefix(path)
        leaf_field = path.split('.')[-1] if '.' in path else path

        if prefix:
            # Nested dataclass case: find groupbox and nested manager
            groupbox = self.form_tree.groupbox_for_prefix(prefix)
            if not groupbox:
                flash_trace(
                    "form.leaf_flash.skip_no_groupbox",
                    manager=self.field_id,
                    path=path,
                    prefix=prefix,
                )
                logger.debug(f"[FLASH] No groupbox found for prefix={prefix}")
                return None
            nested_manager = self.form_tree.nested_manager_for_prefix(prefix)
            if not nested_manager:
                flash_trace(
                    "form.leaf_flash.skip_no_nested_manager",
                    manager=self.field_id,
                    path=path,
                    prefix=prefix,
                )
                logger.debug(f"[FLASH] No nested manager found for prefix={prefix}")
                return None
            leaf_widget = nested_manager.widgets.get(leaf_field)
            label_widget = nested_manager.labels.get(leaf_field)
            logger.debug(
                "[FLASH TRAIL] Found leaf_widget=%s, label_widget=%s",
                type(leaf_widget).__name__ if leaf_widget else None,
                type(label_widget).__name__ if label_widget else None,
            )
            flash_path = path
        else:
            # Flat parameter case (e.g., function parameters): use this manager directly
            # Parent widget (GroupBoxWithHelp) serves as the groupbox container
            groupbox = self.parent()
            leaf_widget = self.widgets.get(leaf_field)
            label_widget = self.labels.get(leaf_field)
            flash_path = path

            from pyqt_reactive.widgets.shared.clickable_help_components import FlashableGroupBox
            if isinstance(leaf_widget, FlashableGroupBox):
                flash_trace(
                    "form.leaf_flash.flash_groupbox_widget",
                    manager=self.field_id,
                    path=path,
                    widget=type(leaf_widget).__qualname__,
                )
                self.register_flash_groupbox(path, leaf_widget)
                if queue_flash:
                    self.queue_flash_local(path)
                return path

        def _find_function_pane_ancestor(widget: QWidget | None) -> QWidget | None:
            from pyqt_reactive.widgets.function_pane import FunctionPaneWidget

            current = widget
            while current is not None:
                if isinstance(current, FunctionPaneWidget):
                    return current
                current = current.parentWidget()
            return None

        pane = _find_function_pane_ancestor(groupbox) if groupbox is not None else None

        target_owner = nested_manager if prefix else self
        field_flash_target = target_owner.field_flash_target(leaf_field)
        if field_flash_target is not None:
            flash_trace(
                "form.leaf_flash.register_field_target",
                manager=self.field_id,
                path=path,
                prefix=prefix,
                leaf=leaf_field,
                target=type(field_flash_target).__qualname__,
            )
            field_flash_target.register_flash(self, path)
            if queue_flash:
                self.queue_flash_local(path)
            return path

        # For nested parameters inside function panes, flash the pane to include title rows
        if pane is not None:
            groupbox = pane

        if not leaf_widget:
            # Some fields render as container-only sections; flash the rendered
            # field container when no separate leaf widget exists.
            if prefix:
                flash_trace(
                    "form.leaf_flash.container_target",
                    manager=self.field_id,
                    path=path,
                    prefix=prefix,
                    leaf=leaf_field,
                    groupbox=type(groupbox).__qualname__ if groupbox is not None else None,
                )
                logger.debug("[FLASH] No leaf widget for %s; flashing field container", leaf_field)
                self.register_flash_groupbox(path, groupbox)
                if queue_flash:
                    self.queue_flash_local(path)
                return path
            else:
                flash_trace(
                    "form.leaf_flash.skip_no_flat_leaf",
                    manager=self.field_id,
                    path=path,
                    leaf=leaf_field,
                )
                logger.debug(f"[FLASH] No leaf widget for flat param {leaf_field}")
            return None

        # Flat parameter case: flash the full groupbox, mask only the changed field
        if not prefix:
            # Get label widget for proper masking (same as nested fields)
            label_widget = self.labels.get(leaf_field)
            flash_trace(
                "form.leaf_flash.register_flat_leaf",
                manager=self.field_id,
                path=flash_path,
                leaf=leaf_field,
                widget=type(leaf_widget).__qualname__,
                groupbox=type(groupbox).__qualname__ if groupbox is not None else None,
            )
            self.register_flash_leaf(flash_path, groupbox, leaf_widget, label_widget=label_widget)
            if queue_flash:
                self.queue_flash_local(flash_path)
            return flash_path

        # Register leaf flash element (dynamic registration for this specific change)
        logger.debug("[FLASH TRAIL] Calling register_flash_leaf with flash_path=%s", flash_path)
        flash_trace(
            "form.leaf_flash.register_nested_leaf",
            manager=self.field_id,
            path=flash_path,
            prefix=prefix,
            leaf=leaf_field,
            widget=type(leaf_widget).__qualname__,
            groupbox=type(groupbox).__qualname__ if groupbox is not None else None,
        )
        self.register_flash_leaf(flash_path, groupbox, leaf_widget, label_widget=label_widget)

        # Queue leaf flash (groupbox with inverse masking for the specific widget)
        if queue_flash:
            self.queue_flash_local(flash_path)
        logger.debug("[FLASH TRAIL] Queued flash for flash_path=%s", flash_path)
        logger.debug(f"[FLASH] Queued leaf flash: key={flash_path}, leaf={leaf_field}")
        return flash_path

    def _queue_structural_flash_for_object_state_path(
        self,
        path: str,
        *,
        queue_flash: bool = True,
    ) -> bool:
        """Resolve an ObjectState path to an inline structural target and flash it."""

        from pyqt_reactive.widgets.structural_table import (
            resolve_inline_dataclass_structural_target,
        )

        for manager in self._iter_form_managers():
            for field_name, widget in manager.widgets.items():
                owner_path = manager._object_state_path_for_field(field_name)
                if not DottedFieldPath(owner_path).contains_path(path):
                    continue
                child_field_name = self._relative_child_field_name(
                    owner_path,
                    path,
                )
                structural_result = resolve_inline_dataclass_structural_target(
                    inline_widget=widget,
                    inline_field_path=tuple(owner_path.split(".")),
                    display_path=path,
                    owner_child_field_name=child_field_name,
                )
                if structural_result is None:
                    continue
                flash_trace(
                    "form.structural_flash.match",
                    manager=self.field_id,
                    path=path,
                    owner=owner_path,
                    field=field_name,
                    child=structural_result.child_field_name,
                    target=type(structural_result.target).__qualname__,
                )
                structural_result.target.register_flash(self, path)
                if queue_flash:
                    self.queue_flash_local(path)
                logger.debug(
                    "[FLASH] Queued structural ObjectState flash: key=%s child_path=%s",
                    path,
                    structural_result.child_field_name,
                )
                return True
        return False

    def _iter_form_managers(self):
        """Yield this form manager and descendants in ObjectState path order."""

        yield self
        for nested_manager in self.nested_managers.values():
            yield from nested_manager._iter_form_managers()

    def _object_state_path_for_field(self, field_name: str) -> str:
        """Return the ObjectState display path for a direct field."""

        return f"{self.field_id}.{field_name}" if self.field_id else field_name

    @staticmethod
    def _relative_child_field_name(owner_path: str, path: str) -> str | None:
        """Return the direct child field under an ObjectState owner path."""

        return DottedFieldPath(owner_path).direct_child_name(path)

    # PAINT-TIME API: ObjectState-path flash lookup inherited from VisualUpdateMixin.
    # Groupboxes and item delegates use the registered ObjectState path to get current flash color.

    def _execute_text_update(self) -> None:
        """Execute queued external repaint callbacks for form companion widgets."""
        for callback in self._extra_repaint_callbacks:
            callback()

    def register_repaint_callback(self, callback) -> None:
        """Register a callback to be invoked during queued visual updates.

        Used by ConfigWindow to repaint tree widget using same flash source of truth.
        """
        self._extra_repaint_callbacks.append(callback)


FormNavigationManager.register(ParameterFormManager)
