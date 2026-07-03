"""
Unified Field Change Dispatcher.

Centralizes all field change handling into a single event-driven dispatcher.
Replaces callback spaghetti with a clean architecture.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pyqt_reactive.animation.flash_trace import flash_trace

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


@dataclass(frozen=True)
class FieldDispatchContext:
    """Resolved dispatch facts shared by field-change stages."""

    event: FieldChangeEvent
    source: 'ParameterFormManager'
    root: 'ParameterFormManager'
    source_path: str
    root_path: str


class DispatchReentrancyGuard:
    """Owns dispatch-entry state for one source manager."""

    def log_start(self, event: FieldChangeEvent) -> None:
        if not DEBUG_DISPATCHER:
            return
        reset_tag = " [RESET]" if event.is_reset else ""
        source = event.source_manager
        logger.info(
            "🚀 DISPATCH%s: %s.%s = %s",
            reset_tag,
            source.field_id,
            event.field_name,
            repr(event.value)[:50],
        )

    def enter(self, source: 'ParameterFormManager') -> bool:
        if source._dispatching:
            if DEBUG_DISPATCHER:
                logger.warning(
                    "🚫 DISPATCH BLOCKED: %s already dispatching (reentrancy guard)",
                    source.field_id,
                )
            return False
        source._dispatching = True
        return True

    def is_reset_blocked(self, source: 'ParameterFormManager') -> bool:
        if not source._in_reset:
            return False
        if DEBUG_DISPATCHER:
            logger.warning(
                "🚫 DISPATCH BLOCKED: %s has _in_reset=True",
                source.field_id,
            )
        return True

    def exit(self, source: 'ParameterFormManager') -> None:
        source._dispatching = False


class FieldDispatchContextFactory:
    """Builds the path context shared by dispatch stages."""

    def build(self, event: FieldChangeEvent) -> FieldDispatchContext:
        source = event.source_manager
        return FieldDispatchContext(
            event=event,
            source=source,
            root=self._get_root_manager(source),
            source_path=self._field_path(source, event.field_name),
            root_path=self._get_full_path(source, event.field_name),
        )

    def _get_root_manager(self, manager: 'ParameterFormManager') -> 'ParameterFormManager':
        current = manager
        while current._parent_manager is not None:
            current = current._parent_manager
        return current

    def _field_path(self, manager: 'ParameterFormManager', field_name: str) -> str:
        if manager.field_id:
            return f"{manager.field_id}.{field_name}"
        return field_name

    def _get_full_path(self, source: 'ParameterFormManager', field_name: str) -> str:
        parts = [field_name]
        current = source
        while current is not None:
            if current.field_id:
                parts.insert(0, current.field_id)
            current = current._parent_manager
        return ".".join(parts)


class SourceStateUpdateStage:
    """Applies the edited value to ObjectState and syncs the source widget."""

    def run(self, context: FieldDispatchContext) -> set[str]:
        # ObjectState.update_parameter() enforces the invariant:
        # state mutation -> global cache invalidation.
        from objectstate import ObjectStateRegistry

        if context.event.is_reset:
            changed_paths = context.source.state.update_parameter(
                context.source_path,
                context.event.value,
            )
        else:
            with ObjectStateRegistry.defer_live_invalidations():
                changed_paths = context.source.state.update_parameter(
                    context.source_path,
                    context.event.value,
                )
        context.source.sync_after_model_field_change(
            context.event.field_name,
            context.source_path,
            changed_paths=changed_paths,
        )
        if DEBUG_DISPATCHER:
            reset_note = " (reset to None)" if context.event.is_reset else ""
            logger.info(
                "  ✅ Updated state.parameters[%s]%s",
                context.source_path,
                reset_note,
            )
        return changed_paths


class SiblingPlaceholderRefreshStage:
    """Refreshes inherited placeholders in sibling forms under the same parent."""

    def run(self, context: FieldDispatchContext) -> None:
        parent = context.source._parent_manager
        if parent is None:
            if DEBUG_DISPATCHER:
                logger.info("  ℹ️  No parent manager (root-level field)")
            return

        if DEBUG_DISPATCHER:
            logger.info(
                "  🔍 Looking for siblings with field %r in %s",
                context.event.field_name,
                parent.field_id,
            )
            logger.info(
                "  🔍 Parent has %d nested managers: %s",
                len(parent.nested_managers),
                list(parent.nested_managers.keys()),
            )

        siblings_refreshed = 0
        for name, sibling in parent.nested_managers.items():
            if self._refresh_sibling_if_affected(context, name, sibling):
                siblings_refreshed += 1

        if DEBUG_DISPATCHER:
            logger.info("  ✅ Refreshed %d sibling(s)", siblings_refreshed)

    def _refresh_sibling_if_affected(
        self,
        context: FieldDispatchContext,
        name: str,
        sibling: 'ParameterFormManager',
    ) -> bool:
        if sibling is context.source:
            if DEBUG_DISPATCHER:
                logger.debug("    ⏭️  Skipping %s (is source)", name)
            return False

        has_field = context.event.field_name in sibling.widgets
        if DEBUG_DISPATCHER:
            self._log_sibling_match(name, sibling, has_field)

        if not has_field:
            return False

        self._refresh_single_field(sibling, context.event.field_name)
        return True

    def _log_sibling_match(
        self,
        name: str,
        sibling: 'ParameterFormManager',
        has_field: bool,
    ) -> None:
        if sibling.object_instance is None:
            sibling_type = "None"
        else:
            sibling_type = type(sibling.object_instance).__name__
        logger.info(
            "    🔍 Sibling %s: type=%s, has_field=%s",
            name,
            sibling_type,
            has_field,
        )

    def _refresh_single_field(self, manager: 'ParameterFormManager', field_name: str) -> None:
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


class LiveContextNotificationStage:
    """Broadcasts ObjectState live-context changes to form/list listeners."""

    DEBOUNCE_MS = 0

    def __init__(self) -> None:
        self._timer = None

    def run(self, context: FieldDispatchContext) -> None:
        # Do not block the source root here: live placeholder/list refreshes are
        # read-only, and the source window also needs to repaint inherited values
        # affected by this edit.
        if context.event.is_reset:
            self.flush()
            return

        if not self._schedule_debounced_flush():
            self.flush()

    def _schedule_debounced_flush(self) -> bool:
        try:
            from PyQt6.QtCore import QCoreApplication, QTimer
        except Exception:
            return False

        if QCoreApplication.instance() is None:
            return False

        if self._timer is None:
            self._timer = QTimer()
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self.flush)
        self._timer.start(self.DEBOUNCE_MS)
        return True

    def flush(self) -> None:
        from objectstate import ObjectStateRegistry
        ObjectStateRegistry.flush_deferred_invalidations()
        ObjectStateRegistry._notify_change()
        if DEBUG_DISPATCHER:
            logger.info(
                "  📣 Notified %d listeners",
                len(ObjectStateRegistry._change_callbacks),
            )


class EnabledFieldStyleStage:
    """Keeps the special enabled field's visuals in sync with model changes."""

    def run(self, context: FieldDispatchContext) -> None:
        if context.event.field_name != 'enabled':
            return
        context.source.sync_enabled_field_visuals(context.event.value)
        if DEBUG_DISPATCHER:
            logger.info("  ✅ Applied enabled styling")


class RootSignalStage:
    """Emits root-manager signals consumed by editor and cross-window listeners."""

    def run(self, context: FieldDispatchContext) -> None:
        logger.debug("🔔 DISPATCHER: Emitting parameter_changed from root")
        logger.debug("  source.field_id=%s", context.source.field_id)
        logger.debug("  root.field_id=%s", context.root.field_id)
        logger.debug("  event.field_name=%s", context.event.field_name)
        logger.debug("  full_path=%s", context.root_path)
        logger.debug("  value type=%s", type(context.event.value).__name__)

        context.root.parameter_changed.emit(context.root_path, context.event.value)
        logger.debug(
            "  ✅ Emitted parameter_changed(%s, ...) from root",
            context.root_path,
        )

        self._emit_cross_window(context)

    def _emit_cross_window(self, context: FieldDispatchContext) -> None:
        root_manager = context.root
        full_path = context.root_path
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


class FieldChangeDispatcher:
    """Singleton coordinator for all field changes."""

    _instance = None

    def __init__(self) -> None:
        self._guard = DispatchReentrancyGuard()
        self._context_factory = FieldDispatchContextFactory()
        self._source_state_update = SourceStateUpdateStage()
        self._sibling_placeholder_refresh = SiblingPlaceholderRefreshStage()
        self._live_context_notification = LiveContextNotificationStage()
        self._enabled_field_style = EnabledFieldStyleStage()
        self._root_signals = RootSignalStage()

    @classmethod
    def instance(cls) -> 'FieldChangeDispatcher':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def dispatch(self, event: FieldChangeEvent) -> None:
        """Handle a field change event."""
        source = event.source_manager
        self._guard.log_start(event)

        if not self._guard.enter(source):
            return

        try:
            if self._guard.is_reset_blocked(source):
                return

            logger.debug(
                "🔬 RESET_TRACE: DISPATCHER: is_reset=%s, field=%s, value=%s",
                event.is_reset,
                event.field_name,
                repr(event.value)[:50],
            )

            context = self._context_factory.build(event)
            flash_trace(
                "dispatch.context",
                source=context.source.field_id,
                root=context.root.field_id,
                source_path=context.source_path,
                root_path=context.root_path,
                reset=context.event.is_reset,
            )
            self._source_state_update.run(context)
            self._sibling_placeholder_refresh.run(context)
            self._live_context_notification.run(context)
            self._enabled_field_style.run(context)
            self._root_signals.run(context)

        except Exception:
            self._flush_pending_invalidations_after_failure()
            raise
        finally:
            self._guard.exit(source)

    def _flush_pending_invalidations_after_failure(self) -> None:
        """Do not let a failed dispatch leak deferred cache invalidations."""
        try:
            from objectstate import ObjectStateRegistry
            if not ObjectStateRegistry.has_deferred_invalidations():
                return
            ObjectStateRegistry.flush_deferred_invalidations()
            ObjectStateRegistry._notify_change()
        except Exception:
            logger.exception("Failed to flush deferred invalidations after dispatch failure")
