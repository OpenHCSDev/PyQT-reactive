"""
Abstract Manager Widget - Base class for item list managers.

Consolidates shared UI infrastructure and CRUD patterns from PlateManagerWidget
and PipelineEditorWidget.

Following OpenHCS ABC patterns:
- BaseFormDialog: Lightweight base, subclass controls initialization
- ParameterFormManager: Combined metaclass for PyQt6 compatibility
- Template Method Pattern: Base defines flow, subclasses implement hooks
"""

from abc import ABC, abstractmethod, ABCMeta
from dataclasses import field
from typing import ClassVar, List, Tuple, Dict, Optional, Any
import logging


from pyqt_reactive.widgets.shared.manager_workflows import (
    ManagerCodeExecutionWorkflow,
    ManagerDeletionWorkflow,
    NullManagerCodeExecutionWorkflow,
    NullManagerDeletionWorkflow,
)


from PyQt6.QtWidgets import (
    QWidget, QPushButton, QListWidgetItem, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal

from pyqt_reactive.core import ReorderableListWidget
from pyqt_reactive.widgets.shared.list_item_delegate import (
    LAYOUT_ROLE,
    StyledText,
)
# Backwards compat alias
SEGMENTS_ROLE = LAYOUT_ROLE
from objectstate import ObjectStateRegistry, patch_lazy_constructors
from pyqt_reactive.widgets.mixins import (
    CrossWindowPreviewMixin,
)
from pyqt_reactive.theming import StyleSheetGenerator
from pyqt_reactive.strategies import (
    FormattingConfig,
    DefaultPreviewFormattingStrategy,
)
from objectstate import LiveContextResolver
from pyqt_reactive.animation import FlashMixin
from pyqt_reactive.widgets.shared.manager_ui_scaffold import setup_manager_widget_ui
from pyqt_reactive.widgets.shared.manager_item_hooks import (
    ManagerItemHooks,
)
from pyqt_reactive.widgets.shared.manager_item_access import ManagerItemAccess
from pyqt_reactive.widgets.shared.manager_preview_formatting import ManagerPreviewFieldFormatter
from pyqt_reactive.widgets.shared.manager_state_binding import ManagerStateBinding
from pyqt_reactive.widgets.shared.manager_list_updater import (
    ManagerListUpdater,
    ManagerListUpdateOperations,
)
from pyqt_reactive.widgets.shared.manager_time_travel_binding import ManagerTimeTravelBinding
from pyqt_reactive.widgets.shared.manager_action_controller import (
    CodeEditorPayload,
    ManagerActionController,
    ManagerActionOperations,
)
from pyqt_reactive.widgets.shared.manager_list_visual_state import ManagerListVisualState
from pyqt_reactive.widgets.shared.manager_item_display_builder import (
    ListItemFormat,
    _ManagerItemDisplayBuilder,
)
from pyqt_reactive.widgets.shared.manager_selection_controller import (
    ItemIdSelectionPayloadProjection,
    ManagerSelectionController,
    ManagerSelectionOperations,
    SelectionPayloadProjection,
)
from pyqt_reactive.widgets.shared.manager_reorder_controller import (
    ManagerReorderController,
    ManagerReorderOperations,
)
from pyqt_reactive.widgets.shared.manager_status_controller import ManagerStatusController
from pyqt_reactive.widgets.shared.manager_config_resolution import ManagerGuiConfigResolution
from pyqt_reactive.services import AutoRegisterServiceMixin
from pyqt_reactive.services.window_navigation import (
    ListNavigationReadinessWindow,
)

logger = logging.getLogger(__name__)


class _CombinedMeta(ABCMeta, type(QWidget)):
    """Combined metaclass for ABC + PyQt6 QWidget."""


class AbstractManagerWidget(
    QWidget,
    CrossWindowPreviewMixin,
    FlashMixin,
    AutoRegisterServiceMixin,
    ABC,
    metaclass=_CombinedMeta,
):
    """
    Abstract base class for item list manager widgets.

    Consolidates UI infrastructure and CRUD operations from PlateManagerWidget
    and PipelineEditorWidget using template method pattern.

    Subclasses MUST:
    1. Define TITLE, BUTTON_CONFIGS, PREVIEW_FIELD_CONFIGS, ACTION_REGISTRY class attributes
    2. Implement all abstract methods for item-specific behavior
    3. Call super().__init__(...) BEFORE subclass-specific state
    4. Call setup_ui() after subclass state is initialized

    Init Order (CRITICAL):
        1. Subclass-specific state initialization
        2. super().__init__(...) - creates base infrastructure (auto-processes PREVIEW_FIELD_CONFIGS)
        3. setup_ui() - create widgets
        4. setup_connections() - wire subclass-specific signals after setup_manager_connections()
    """

    # === Subclass MUST override these class attributes ===
    TITLE: str = "Manager"
    SERVICE_TYPE = ...  # Default: concrete subclasses auto-register using their own type
    BUTTON_CONFIGS: List[Tuple[str, str, str]] = []  # [(label, action_id, tooltip), ...]
    BUTTON_GRID_COLUMNS: int = 4  # Number of columns in button grid (0 = single row with all buttons)
    ACTION_REGISTRY: Dict[str, str] = {}  # action_id -> method_name
    DYNAMIC_ACTIONS: Dict[str, str] = {}  # action_id -> resolver_method_name (for toggles)
    ITEM_NAME_SINGULAR: str = "item"
    ITEM_NAME_PLURAL: str = "items"
    SELECTION_PAYLOAD_PROJECTION: ClassVar[SelectionPayloadProjection] = ItemIdSelectionPayloadProjection()
    SELECTION_CLEARED_PAYLOAD: ClassVar[Any] = None
    SCOPE_ITEM_TYPE: ClassVar[Any | None] = None
    STATE_BINDING: ClassVar[ManagerStateBinding | None] = None

    # === Declarative List Item Format Config ===
    # Type-safe configuration for list item display. See ListItemFormat dataclass.
    # Override in subclasses with ListItemFormat(...) instance.
    LIST_ITEM_FORMAT: Optional[ListItemFormat] = None

    # === Preview Formatting Strategy ===
    # Configuration for how preview fields are formatted and grouped.
    # Override in subclasses with FormattingConfig(...) instance or default_factory.
    PREVIEW_FORMATTING_CONFIG: FormattingConfig = field(default_factory=FormattingConfig)

    # === Declarative Item Hooks ===
    # Subclass declares remaining data-shaped list behavior here. Stateful manager
    # behavior such as backing storage and selection mutation is expressed through
    # nominal methods on the manager itself.
    ITEM_HOOKS: ManagerItemHooks = ManagerItemHooks()
    CODE_EDITOR_PAYLOAD: CodeEditorPayload = CodeEditorPayload()

    # Custom data role for scope border color (kept local to avoid delegate coupling)
    SCOPE_BORDER_ROLE = Qt.ItemDataRole.UserRole + 10

    # Status scrolling: enable marquee animation for long status messages
    ENABLE_STATUS_SCROLLING: bool = False

    # Common signals
    status_message = pyqtSignal(str)

    def __init__(self, service_adapter, color_scheme=None, gui_config=None, parent=None):
        """
        Initialize base widget.

        Args:
            service_adapter: REQUIRED - provides async execution, dialogs, etc.
            color_scheme: Color scheme for styling (optional, uses service adapter if None)
            gui_config: GUI configuration (optional, for DualEditorWindow in PipelineEditor)
            parent: Parent widget

        Subclass __init__ MUST follow this pattern:
            # 1. Subclass-specific state (BEFORE super().__init__)
            self.pipeline_steps = []
            self.selected_step = ""
            # ...

            # 2. Initialize base class (auto-processes PREVIEW_FIELD_CONFIGS)
            super().__init__(service_adapter, color_scheme, gui_config, parent)

            # 3. Setup UI (AFTER subclass state is ready)
            self.setup_ui()
            self.setup_connections()  # Calls setup_manager_connections() plus subclass wiring
            self.update_button_states()
        """
        super().__init__(parent)

        # CRITICAL: Manually trigger AutoRegisterServiceMixin registration
        # Qt's C++ classes don't call super().__init__(), so we need to do it explicitly
        from pyqt_reactive.services.service_registry import AutoRegisterServiceMixin
        if isinstance(self, AutoRegisterServiceMixin):
            self._register_with_service_registry()

        # Core dependencies (REQUIRED)
        self.service_adapter = service_adapter
        self.color_scheme = color_scheme or service_adapter.get_current_color_scheme()
        self.gui_config = ManagerGuiConfigResolution.resolve(gui_config)
        self.style_generator = StyleSheetGenerator(self.color_scheme)  # Create internally
        self.event_bus = service_adapter.get_event_bus() if service_adapter else None
        self.code_execution_workflow: ManagerCodeExecutionWorkflow = (
            NullManagerCodeExecutionWorkflow()
        )
        self.deletion_workflow: ManagerDeletionWorkflow = NullManagerDeletionWorkflow()

        # UI components (created in setup_ui)
        self.buttons: Dict[str, QPushButton] = {}
        self.status_label: Optional[QLabel] = None
        self.item_list: Optional[ReorderableListWidget] = None

        # Status widgets are created in setup_ui.
        self._status_scroll: Optional[QWidget] = None  # QScrollArea when scrolling enabled

        # Live context resolver for config attribute resolution
        self._live_context_resolver = LiveContextResolver()

        # Per-update-cycle scope cache: item_id -> scope_id (cleared at start of each update)
        self._item_scope_cache: Dict[int, str] = {}
        self._item_access = ManagerItemAccess.from_manager(self, self._item_scope_cache)
        self._list_visual_state = ManagerListVisualState(
            self,
            scope_border_role=self.SCOPE_BORDER_ROLE,
            item_access=self._item_access,
        )
        self._init_visual_update_mixin()  # Initialize VisualUpdateMixin state

        # Create preview formatting strategy
        # Handle field(default_factory=FormattingConfig) pattern
        from dataclasses import is_dataclass, Field
        if isinstance(self.PREVIEW_FORMATTING_CONFIG, Field):
            # Extract default_factory from Field and call it
            config = self.PREVIEW_FORMATTING_CONFIG.default_factory()
        elif callable(self.PREVIEW_FORMATTING_CONFIG):
            config = self.PREVIEW_FORMATTING_CONFIG()
        else:
            config = self.PREVIEW_FORMATTING_CONFIG
        self._preview_formatting_strategy = DefaultPreviewFormattingStrategy(config, widget=self)
        self._preview_field_formatter = ManagerPreviewFieldFormatter()
        self._item_display_builder = _ManagerItemDisplayBuilder(
            preview_formatting_strategy=self._preview_formatting_strategy,
            field_formatter=self._preview_field_formatter.format_field,
            signature_diff_fields=self._list_visual_state.signature_diff_fields,
            scope_for_item=self._item_access.scope_for_item,
        )
        self._list_updater = ManagerListUpdater()
        self._time_travel_binding = ManagerTimeTravelBinding(self, self._item_access)
        self._action_controller = ManagerActionController()
        self._selection_controller = ManagerSelectionController()
        self._reorder_controller = ManagerReorderController()
        self._status_controller = ManagerStatusController(
            enable_scrolling=self.ENABLE_STATUS_SCROLLING,
        )

        # Initialize CrossWindowPreviewMixin for preview field configuration API
        # (We override _on_live_context_changed to use unified batching)
        self._init_cross_window_preview_mixin()

        self._time_travel_binding.connect()

    # ========== UI Infrastructure (Concrete) ==========

    def setup_ui(self) -> None:
        """
        Create UI with QSplitter for resizable list/buttons layout.

        Uses VERTICAL orientation (list above buttons) to match current behavior.
        Subclass can override to add custom elements (e.g., PlateManager status scrolling).
        """
        ui_parts = setup_manager_widget_ui(
            owner=self,
            title=self.TITLE,
            color_scheme=self.color_scheme,
            style_generator=self.style_generator,
            enable_status_scrolling=self.ENABLE_STATUS_SCROLLING,
            button_configs=self.BUTTON_CONFIGS,
            on_action=self.handle_button_action,
            button_grid_columns=self.BUTTON_GRID_COLUMNS,
        )
        self.status_label = ui_parts.status_label
        self._status_scroll = ui_parts.status_scroll
        self.item_list = ui_parts.item_list
        self.buttons = ui_parts.button_panel.buttons

    def setup_manager_connections(self) -> None:
        """
        Setup base signal connections for list-manager widget events.

        Subclasses that expose their own setup_connections() should call this
        first, then wire subclass-specific signals.
        """
        # Selection changes
        self.item_list.itemSelectionChanged.connect(self._on_selection_changed)

        # Double-click
        self.item_list.itemDoubleClicked.connect(self._on_item_double_clicked)

        # Reordering
        self.item_list.items_reordered.connect(self._on_items_reordered)

        # Status messages
        self.status_message.connect(self.update_status)

    def on_time_travel_complete(self, dirty_states, triggering_scope):
        """Refresh list after time travel. Subclasses can override for custom reloads."""
        del dirty_states, triggering_scope
        self._time_travel_binding.refresh_after_time_travel(self)

    def get_item_insert_index(self, item: Any, scope_key: str) -> Optional[int]:
        """Get the index at which to insert item during time-travel re-registration.

        Subclass can override to maintain correct ordering.
        Default: returns None (append to end).
        """
        return None

    # ========== Action Dispatch (Concrete) ==========

    def handle_button_action(self, action: str) -> None:
        """Dispatch a button action through the manager action controller."""
        self._action_controller.dispatch(self._action_operations(), action)

    def _action_operations(self) -> ManagerActionOperations:
        """Return the nominal operation port consumed by ManagerActionController."""
        return ManagerActionOperations(
            widget=self,
            action_registry=self.ACTION_REGISTRY,
            dynamic_actions=self.DYNAMIC_ACTIONS,
            resolve_method=lambda method_name: getattr(self, method_name),
            run_async=self.service_adapter.execute_async_operation,
            selected_items=self.get_selected_items,
            item_name_singular=self.ITEM_NAME_SINGULAR,
            item_name_plural=self.ITEM_NAME_PLURAL,
            show_error=self.service_adapter.show_error_dialog,
            validate_delete=self.validate_delete,
            perform_delete=self.perform_delete,
            update_item_list=self.update_item_list,
            emit_items_changed=self._emit_items_changed,
            emit_status=self.status_message.emit,
            show_item_editor=self.show_item_editor,
            validate_code_action=lambda: True,
            code_payload=self.CODE_EDITOR_PAYLOAD,
            pre_code_execution=self._pre_code_execution,
            patch_lazy_constructors=patch_lazy_constructors,
            migrate_code_namespace=self.handle_code_execution_error,
            apply_code_namespace=self.apply_executed_code,
            post_code_execution=ObjectStateRegistry.increment_token,
        )

    # ========== CRUD Template Methods (Concrete) ==========

    def action_delete(self) -> None:
        """Delete selected items through the manager action controller."""
        self._action_controller.delete_selected(self._action_operations())

    def action_edit(self) -> None:
        """Edit the first selected item through the manager action controller."""
        self._action_controller.edit_selected(self._action_operations())

    def action_code(self) -> None:
        """Open the code editor through the manager action controller."""
        self._action_controller.open_code_editor(self._action_operations())

    # ========== Unified Helper Methods (Concrete) ==========

    def get_selected_items(self) -> List[Any]:
        """Get currently selected backing items."""
        return self._selection_controller.selected_items(
            self._selection_operations()
        )

    # ========== Event Handlers (Concrete) ==========

    def _on_selection_changed(self) -> None:
        """Handle selection change with deselection prevention."""
        self._selection_controller.handle_selection_changed(
            self._selection_operations()
        )

    def _on_item_double_clicked(self, list_item: QListWidgetItem) -> None:
        """Handle list item double-click activation."""
        self._selection_controller.handle_item_double_clicked(
            self._selection_operations(),
            list_item,
        )

    def _selection_operations(self) -> ManagerSelectionOperations:
        """Return the nominal operation port consumed by ManagerSelectionController."""
        return ManagerSelectionOperations(
            list_widget=self.item_list,
            selected_items=self.get_selected_items,
            item_from_list_item=self._item_access.item_from_list_item,
            item_id=self._item_access.item_hooks.item_id,
            should_preserve_selection=lambda: self._item_access.item_hooks.should_preserve_selection(self),
            current_selection_id=lambda: self._item_access.state_binding.current_selection_id(self),
            set_selection_id=lambda item_id: self._item_access.state_binding.set_selection_id(self, item_id),
            selection_signal=lambda: self._item_access.state_binding.selection_signal(self),
            selected_payload=self.SELECTION_PAYLOAD_PROJECTION.selected,
            cleared_payload=self.SELECTION_CLEARED_PAYLOAD,
            in_time_travel=lambda: self._time_travel_binding.in_time_travel,
            update_button_states=self.update_button_states,
            handle_item_double_click=lambda item: self.action_edit(),
        )

    def _on_items_reordered(self, from_index: int, to_index: int) -> None:
        """Handle item reordering from drag/drop."""
        self._reorder_controller.handle_reordered(
            self._reorder_operations(),
            from_index,
            to_index,
        )

    def _reorder_operations(self) -> ManagerReorderOperations:
        """Return the nominal operation port consumed by ManagerReorderController."""
        return ManagerReorderOperations(
            list_widget=self.item_list,
            item_from_list_item=self._item_access.item_from_list_item,
            item_id=self._item_access.item_hooks.item_id,
            item_name_singular=self.ITEM_NAME_SINGULAR,
            item_name_plural=self.ITEM_NAME_PLURAL,
            reorder_items=self._handle_items_reordered,
            emit_items_changed=self._emit_items_changed,
            update_item_list=self.update_item_list,
            emit_status=self.status_message.emit,
        )

    def update_status(self, message: str) -> None:
        """Update status label with optional auto-scrolling marquee."""
        self._status_controller.update(
            message=message,
            context=self,
            status_label=self.status_label,
            status_scroll=self._status_scroll,
        )

    def resizeEvent(self, event) -> None:
        """Handle resize to recalculate status scrolling."""
        super().resizeEvent(event)
        self._status_controller.recalculate_after_resize(
            context=self,
            status_label=self.status_label,
            status_scroll=self._status_scroll,
        )

    # ========== Code Editor Hooks (Concrete with defaults) ==========

    def _handle_edited_code(self, code: str) -> None:
        """Execute edited code through the manager action controller."""
        self._action_controller.apply_edited_code(self._action_operations(), code)

    # === Code Execution Hooks (for _handle_edited_code template) ===

    def _pre_code_execution(self) -> None:
        """
        Pre-processing before code execution (optional hook).

        PlateManager: Open pipeline editor window
        PipelineEditor: No-op
        """
        pass  # Default: no-op

    def handle_code_execution_error(self, code: str, error: Exception, namespace: dict) -> Optional[dict]:
        """
        Handle code execution error, optionally returning migrated namespace.

        Return new namespace dict to continue, or None to re-raise the error.

        PipelineEditor: Handle old-format step constructors (group_by/variable_components)
        PlateManager: Return None (no migration support)
        """
        return self.code_execution_workflow.migration_namespace(code, error)

    def apply_executed_code(self, namespace: dict) -> bool:
        """
        Apply executed code namespace to widget state.

        Extract expected variables from namespace and update internal state.
        Return True if successful, False if required variables missing.

        PipelineEditor: Extract 'pipeline_steps', update self.pipeline_steps
        PlateManager: Extract 'plate_paths', 'pipeline_data', etc.
        """
        if self.code_execution_workflow.apply_namespace(namespace):
            return True
        logger.warning(f"{type(self).__name__}.apply_executed_code not implemented")
        return False  # Default: fail (subclass must override)

    # ========== Utility Methods (Concrete) ==========

    def _find_main_window(self):
        """Return the main window owned by the required service adapter."""
        return self.service_adapter.main_window

    # VisualUpdateMixin implementation - list items use WindowFlashOverlay (no custom methods needed)

    @property
    def has_list_navigation_items(self) -> bool:
        """Return whether list navigation can resolve item ids."""
        return self._list_visual_state.has_navigation_items

    def clear_list_visual_state(self) -> None:
        """Clear list flash subscriptions and navigation geometry."""
        self._list_visual_state.cleanup()

    def _visual_repaint(self) -> None:
        """Trigger single repaint after all items updated (VisualUpdateMixin)."""
        if self.item_list:
            self.item_list.update()

    def _execute_text_update(self) -> None:
        """Execute text/placeholder update (VisualUpdateMixin)."""
        self.update_item_list()

    def _on_live_context_changed(self) -> None:
        """Override CrossWindowPreviewMixin to use unified visual update batching."""
        self.queue_visual_update()

    def _get_item_scope_id(self, item: Any, index: int) -> Optional[str]:
        """Return the ObjectState scope id represented by a list item."""
        del item, index
        return None

    # ========== List Update Template ==========

    def update_item_list(self) -> None:
        """
        Template: Update the item list with in-place optimization.

        Flow:
        1. Check for placeholder condition → show placeholder if needed
        2. Pre-update hook (collect context, normalize state)
        3. Update with optimization: in-place text update if structure unchanged
        4. Post-update hook (auto-select first if needed)
        5. Update button states
        """
        self._list_updater.update(self._list_update_operations())

    # ========== Abstract Methods (Subclass MUST implement) ==========

    @abstractmethod
    def action_add(self) -> None:
        """
        Add item(s). Subclass owns flow (directory chooser vs dialog).

        PlateManager: Directory chooser, multi-select, add_plate_callback
        PipelineEditor: Dialog with FunctionStep selection
        """
        ...

    @abstractmethod
    def update_button_states(self) -> None:
        """
        Enable/disable buttons based on current state.

        PlateManager: Based on selection and orchestrator state (init/compile/run)
        PipelineEditor: Based on selection and current_plate
        """
        ...

    # === CRUD Hooks (declarative via ITEM_HOOKS where possible) ===

    def validate_delete(self, items: List[Any]) -> bool:
        """Check if delete is allowed. Default: True. Override for restrictions."""
        return self.deletion_workflow.validate(items)

    def perform_delete(self, items: List[Any]) -> None:
        """
        Remove items from internal list.

        PlateManager: Remove from self.plates, cleanup orchestrators
        PipelineEditor: Remove from self.pipeline_steps, update orchestrator
        """
        self.deletion_workflow.delete(items)

    @abstractmethod
    def show_item_editor(self, item: Any) -> None:
        """
        Show editor for item.

        PlateManager: Open config window for plate orchestrator
        PipelineEditor: Open DualEditorWindow for step
        """
        ...

    # === List Update Hooks ===

    def _list_update_operations(self) -> ManagerListUpdateOperations:
        """Return the nominal operation port consumed by ManagerListUpdater."""
        return ManagerListUpdateOperations(
            item_list=self.item_list,
            backing_items=self._item_access.state_binding.items(self),
            item_id=self._item_access.item_hooks.item_id,
            should_preserve_selection=lambda: self._item_access.item_hooks.should_preserve_selection(self),
            placeholder=self._get_list_placeholder,
            prepare_update=self.prepare_list_update,
            clear_scope_cache=self._item_access.clear_scope_cache,
            subscribed_scope_ids=self._list_visual_state.subscribed_scope_ids,
            scope_for_item=self._item_access.scope_for_item,
            cleanup_flash_subscriptions=self._list_visual_state.cleanup,
            clear_scope_to_list_item=self._list_visual_state.clear_scope_to_list_item,
            format_item=self._format_item_content,
            list_item_data_for=self._item_access.item_hooks.list_item_data_for,
            tooltip_for=self._get_list_item_tooltip,
            extra_data_for=self._get_list_item_extra_data,
            set_styling_roles=self._list_visual_state.set_item_styling_roles,
            apply_scope_color=self._list_visual_state.apply_scope_color,
            subscribe_flash=self._list_visual_state.subscribe_flash,
            post_update=self._post_update_list,
            update_button_states=self.update_button_states,
        )

    @abstractmethod
    def _format_item_content(self, item: Any, index: int, context: Any) -> str:
        """Format item content for list display. Subclass must implement.

        May return StyledText with segments for per-field styling.
        """
        ...

    @abstractmethod
    def _get_list_item_tooltip(self, item: Any) -> str:
        """
        Get tooltip for list item.

        PlateManager: return f"Status: {orchestrator.state.value}" or ""
        PipelineEditor: return self._create_step_tooltip(item)
        """
        ...

    def _get_list_item_extra_data(self, item: Any, index: int) -> Dict[int, Any]:
        """
        Get extra UserRole+N data for list item (optional).

        Returns dict mapping role_offset to value.

        PlateManager: return {} (no extra data)
        PipelineEditor: return {1: not step.enabled}
        """
        return {}  # Default: no extra data

    def _get_list_placeholder(self) -> Optional[Tuple[str, Any]]:
        """
        Get placeholder (text, data) when list should show placeholder.

        Return None if no placeholder needed.

        PlateManager: return None (no placeholder)
        PipelineEditor: return ("No plate selected...", None) if no orchestrator
        """
        return None  # Default: no placeholder

    def prepare_list_update(self) -> Any:
        """
        Pre-update hook: normalize state, collect context.

        Returns context object passed to _format_item_content.

        PlateManager: return None
        PipelineEditor: normalize scope tokens, collect live context, return snapshot
        """
        return None  # Default: no context

    def _post_update_list(self) -> None:
        """
        Post-update hook: auto-select first if needed.

        PlateManager: auto-select first plate if no selection
        PipelineEditor: no-op
        """
        pass  # Default: no-op

    def build_item_display_from_format(
        self,
        item: Any,
        item_name: str,
        status_prefix: str = "",
        detail_line: str = "",
    ) -> 'StyledText':
        """Build StyledText using declarative LIST_ITEM_FORMAT config."""
        return self._item_display_builder.build_from_format(
            item=item,
            item_name=item_name,
            item_format=self.LIST_ITEM_FORMAT,
            status_prefix=status_prefix,
            detail_line=detail_line,
        )

    # === Reorder Hook (declarative base + optional post-hook) ===

    def _handle_items_reordered(self, from_index: int, to_index: int) -> None:
        """Reorder backing list and call _post_reorder() hook."""
        items = self._item_access.state_binding.items(self)
        item = items.pop(from_index)
        items.insert(to_index, item)
        self._post_reorder()

    def _post_reorder(self) -> None:
        """Post-reorder hook. Override for additional cleanup (e.g., normalize tokens)."""
        pass

    # === Items Changed Hook ===

    def _emit_items_changed(self) -> None:
        """Emit manager-specific item-list changes."""
        pass

    # === Config Resolution Hook (subclass must implement) ===

    @abstractmethod
    def _get_scope_for_item(self, item: Any) -> str:
        """Get scope_id for an item (for ObjectState lookup). Subclass must implement."""
        ...

    # === CrossWindowPreviewMixin Hook (overridden by VisualUpdateMixin) ===

    def _handle_full_preview_refresh(self) -> None:
        """Override: Replaced by _execute_text_update via VisualUpdateMixin."""
        # This is only called if CrossWindowPreviewMixin's timer fires (shouldn't happen
        # since we override _on_live_context_changed), but kept for safety
        self.update_item_list()

    def closeEvent(self, event):
        """Ensure time travel callbacks are unregistered."""
        self._time_travel_binding.disconnect()
        super().closeEvent(event)


ListNavigationReadinessWindow.register(AbstractManagerWidget)
