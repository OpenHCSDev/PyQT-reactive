"""
Unified Field Change Dispatcher.

Centralizes all field change handling into a single event-driven dispatcher.
Replaces callback spaghetti with a clean architecture.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pyqt_reactive.forms.parameter_form_manager import ParameterFormManager

logger = logging.getLogger(__name__)

# Debug flag for verbose dispatcher logging
DEBUG_DISPATCHER = False


@dataclass
class FieldChangeEvent:
    """Immutable event representing a field change."""
    field_name: str                        # Leaf field name
    value: Any                             # New value
    source_manager: 'ParameterFormManager' # Where change originated
    is_reset: bool = False                 # True if this is a reset operation (don't track as user-set)


class FieldChangeDispatcher:
    """Singleton dispatcher for all field changes. Stateless."""

    _instance = None

    @classmethod
    def instance(cls) -> 'FieldChangeDispatcher':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def dispatch(self, event: FieldChangeEvent) -> None:
        """Handle a field change event."""
        source = event.source_manager

        if DEBUG_DISPATCHER:
            reset_tag = " [RESET]" if event.is_reset else ""
            logger.info(f"🚀 DISPATCH{reset_tag}: {source.field_id}.{event.field_name} = {repr(event.value)[:50]}")

        # Reentrancy guard
        if getattr(source, '_dispatching', False):
            if DEBUG_DISPATCHER:
                logger.warning(f"🚫 DISPATCH BLOCKED: {source.field_id} already dispatching (reentrancy guard)")
            return
        source._dispatching = True

        try:
            if source._in_reset:
                if DEBUG_DISPATCHER:
                    logger.warning(f"🚫 DISPATCH BLOCKED: {source.field_id} has _in_reset=True")
                return

            logger.debug(f"🔬 RESET_TRACE: DISPATCHER: is_reset={event.is_reset}, field={event.field_name}, value={repr(event.value)[:50]}")

            # 1. Update source's data model via ObjectState
            # ObjectState.update_parameter() enforces the invariant: state mutation → global cache invalidation
            # (calls ObjectStateRegistry.increment_token(notify=False) internally)
            # CRITICAL: Compute full dotted path for nested PFMs
            full_path = f"{source.field_id}.{event.field_name}" if source.field_id else event.field_name
            source.state.update_parameter(full_path, event.value)
            if DEBUG_DISPATCHER:
                reset_note = " (reset to None)" if event.is_reset else ""
                logger.info(f"  ✅ Updated state.parameters[{full_path}]{reset_note}")

            # Update ProvenanceButton visibility after state change
            # The button is in the groupbox title, not in source.widgets
            from pyqt_reactive.widgets.shared.clickable_help_components import ProvenanceButton
            from PyQt6.QtWidgets import QWidget
            
            # 3. Refresh siblings that have the same field
            parent = source._parent_manager
            
            # Find the groupbox widget for this manager
            groupbox = None
            if parent:
                for name, nested in parent.nested_managers.items():
                    if nested is source:
                        groupbox = parent.widgets.get(name)
                        break
            
            # Update provenance button visibility
            if source._parent_manager:
                source._update_provenance_button_visibility()
            
            # Update groupbox dirty markers (title and Reset All button)
            source._update_groupbox_dirty_markers()

            # Update reset button styling for ALL reset buttons in this manager
            from pyqt_reactive.utils.styling_utils import update_reset_button_styling
            for field_name, reset_button in source.reset_buttons.items():
                update_reset_button_styling(reset_button, source.state, source.field_id, field_name)
            if parent:
                if DEBUG_DISPATCHER:
                    logger.info(f"  🔍 Looking for siblings with field '{event.field_name}' in {parent.field_id}")
                    logger.info(f"  🔍 Parent has {len(parent.nested_managers)} nested managers: {list(parent.nested_managers.keys())}")

                siblings_refreshed = 0
                for name, sibling in parent.nested_managers.items():
                    if sibling is source:
                        if DEBUG_DISPATCHER:
                            logger.debug(f"    ⏭️  Skipping {name} (is source)")
                        continue

                    # Check if sibling has the same field (simpler than isinstance for Lazy wrappers)
                    has_field = event.field_name in sibling.widgets

                    if DEBUG_DISPATCHER:
                        sibling_type = type(sibling.object_instance).__name__ if sibling.object_instance else 'None'
                        logger.info(f"    🔍 Sibling {name}: type={sibling_type}, has_field={has_field}")

                    if has_field:
                        self._refresh_single_field(sibling, event.field_name)
                        siblings_refreshed += 1

                if DEBUG_DISPATCHER:
                    logger.info(f"  ✅ Refreshed {siblings_refreshed} sibling(s)")
            else:
                if DEBUG_DISPATCHER:
                    logger.info(f"  ℹ️  No parent manager (root-level field)")

            # 4. Notify listeners (after sibling refresh)
            # This allows sibling refreshes to share the cached live context
            # (first sibling computes and caches, subsequent siblings get cache hits)
            root = self._get_root_manager(source)
            root._block_cross_window_updates = True
            try:
                from objectstate import ObjectStateRegistry
                ObjectStateRegistry._notify_change()
                if DEBUG_DISPATCHER:
                    logger.info(f"  📣 Notified {len(ObjectStateRegistry._change_callbacks)} listeners")
            finally:
                root._block_cross_window_updates = False

            # 3. Handle 'enabled' field styling
            if event.field_name == 'enabled':
                source._enabled_field_styling_service.on_enabled_field_changed(
                    source, 'enabled', event.value
                )
                if DEBUG_DISPATCHER:
                    logger.info(f"  ✅ Applied enabled styling")

            # 4. Emit from ROOT with full path (for all listeners)
            # This ensures listeners connected to root get notified of ALL changes
            # (including nested) with full paths like "processing_config.group_by"
            root = self._get_root_manager(source)
            full_path = self._get_full_path(source, event.field_name)

            logger.debug(f"🔔 DISPATCHER: Emitting parameter_changed from root")
            logger.debug(f"  source.field_id={source.field_id}")
            logger.debug(f"  root.field_id={root.field_id}")
            logger.debug(f"  event.field_name={event.field_name}")
            logger.debug(f"  full_path={full_path}")
            logger.debug(f"  value type={type(event.value).__name__}")

            root.parameter_changed.emit(full_path, event.value)
            logger.debug(f"  ✅ Emitted parameter_changed({full_path}, ...) from root")

            # 5. Emit cross-window signal from ROOT
            self._emit_cross_window(root, full_path, event.value)

        finally:
            source._dispatching = False

    def _get_root_manager(self, manager: 'ParameterFormManager') -> 'ParameterFormManager':
        """Walk up to root manager."""
        current = manager
        while current._parent_manager is not None:
            current = current._parent_manager
        return current

    def _get_full_path(self, source: 'ParameterFormManager', field_name: str) -> str:
        """Build full path by walking up parent chain.

        Example: "GlobalPipelineConfig.pipeline_config.well_filter_config.well_filter"
        """
        parts = [field_name]
        current = source
        while current is not None:
            parts.insert(0, current.field_id)
            current = current._parent_manager
        return ".".join(parts)

    def _emit_cross_window(self, root_manager: 'ParameterFormManager', full_path: str, value: Any) -> None:
        """Emit context_changed from root with scope_id and field path."""
        logger.debug(f"  🔍 _emit_cross_window: checking should_skip_updates() for {root_manager.field_id}")
        logger.debug(f"    state._in_reset={root_manager.state._in_reset}, state._block_cross_window_updates={root_manager.state._block_cross_window_updates}")
        if root_manager.state.should_skip_updates():
            logger.warning(f"  🚫 Cross-window BLOCKED: _should_skip_updates()=True for {root_manager.field_id}")
            return

        # REMOVED: update_thread_local_global_config() call
        # Thread-local should ONLY be updated on SAVE, not on every keystroke!
        # Descendants (plates, steps) should see the SAVED global config, not unsaved edits.

        logger.debug(f"  📡 Emitting context_changed: scope={root_manager.scope_id}, path={full_path}")
        root_manager.context_changed.emit(root_manager.scope_id or "", full_path)
        logger.debug(f"  ✅ context_changed emitted")

    def _refresh_single_field(self, manager: 'ParameterFormManager', field_name: str) -> None:
        """Refresh just one field's placeholder in a sibling manager."""
        if DEBUG_DISPATCHER:
            logger.info(f"      🔄 _refresh_single_field: {manager.field_id}.{field_name}")

        if field_name not in manager.widgets:
            if DEBUG_DISPATCHER:
                logger.warning(f"      ⏭️  Field {field_name} not in widgets, skipping")
            return

        # FIX: Check current value instead of _user_set_fields.
        # Even if a field is in _user_set_fields, if its value is None it should
        # show a placeholder (inherited from parent). This is critical for code-mode
        # which sets all fields (adding them to _user_set_fields) but many have None
        # values that should display as placeholders.
        current_value = manager.parameters.get(field_name)
        if current_value is not None:
            if DEBUG_DISPATCHER:
                logger.info(f"      ⏭️  Field {field_name} has concrete value ({type(current_value).__name__}), skipping placeholder refresh")
            return

        if DEBUG_DISPATCHER:
            logger.info(f"      ✅ Refreshing placeholder for {manager.field_id}.{field_name}")

        manager._parameter_ops_service.refresh_single_placeholder(manager, field_name)

