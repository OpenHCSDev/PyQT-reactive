"""Apply admitted field mutations and update their owning form tree."""

from __future__ import annotations

from abc import ABC, abstractmethod
from objectstate import FieldAccessError, FieldProxy

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar


from formbridge.flash_trace import flash_trace


if TYPE_CHECKING:
    from pyqt_reactive.forms.parameter_form_manager import ParameterFormManager

logger = logging.getLogger(__name__)

# Debug flag for verbose dispatcher logging
DEBUG_DISPATCHER = False


@dataclass(frozen=True)
class FieldChangeEvent(ABC):
    """An admitted field and its UI source; each operation owns its mutation."""
    field: FieldProxy
    source_manager: "ParameterFormManager"
    is_reset: ClassVar[bool] = False

    def __post_init__(self):
        if self.field.state is not self.source_manager.state:
            raise FieldAccessError("The field belongs to a different editing state")

    @property
    def field_name(self):
        return self.field.name

    @abstractmethod
    def apply(self) -> set[str]:
        """Perform the sole canonical model transaction for this operation."""


@dataclass(frozen=True)
class FieldWriteEvent(FieldChangeEvent):
    value: Any

    def apply(self):
        from objectstate import ObjectStateRegistry
        with ObjectStateRegistry.defer_live_invalidations():
            return self.field.write(self.value)


@dataclass(frozen=True)
class FieldResetEvent(FieldChangeEvent):
    is_reset: ClassVar[bool] = True

    def apply(self):
        return self.field.reset()



@dataclass(frozen=True)
class FieldDispatchContext:
    """One prepared UI route; the event retains the field and source facts."""
    event: FieldChangeEvent
    root: "ParameterFormManager"

    @classmethod
    def for_event(cls, event):
        return cls(event, event.source_manager.form_tree.root())



class DispatchReentrancyGuard:
    """Owns dispatch-entry state for one source manager."""

    def log_start(self, event: FieldChangeEvent) -> None:
        if not DEBUG_DISPATCHER:
            return
        reset_tag = " [RESET]" if event.is_reset else ""
        source = event.source_manager
        logger.info(
            "🚀 DISPATCH%s: %s.%s (%s)",
            reset_tag,
            source.field_id,
            event.field_name,
            type(event).__name__,
        )

    def enter(self, source: "ParameterFormManager") -> bool:
        if source._dispatching:
            if DEBUG_DISPATCHER:
                logger.warning(
                    "🚫 DISPATCH BLOCKED: %s already dispatching (reentrancy guard)",
                    source.field_id,
                )
            return False
        source._dispatching = True
        return True

    def is_reset_blocked(self, event: FieldChangeEvent) -> bool:
        source = event.source_manager
        if not source._in_reset or event.is_reset:
            return False
        if DEBUG_DISPATCHER:
            logger.warning(
                "🚫 DISPATCH BLOCKED: %s has _in_reset=True",
                source.field_id,
            )
        return True

    def exit(self, source: "ParameterFormManager") -> None:
        source._dispatching = False





class SourceStateUpdateStage:
    """Apply the operation once, then synchronize the source view."""

    def run(self, context: FieldDispatchContext) -> set[str]:
        source = context.event.source_manager
        if source.before_mutation is not None:
            source.before_mutation()
        changed_paths = context.event.apply()
        source.sync_after_model_field_change(context.event.field_name, changed_paths=changed_paths)
        return changed_paths



class SiblingPlaceholderRefreshStage:
    """Refreshes inherited placeholders in sibling forms under the same parent."""

    def run(self, context: FieldDispatchContext) -> None:
        parent = context.event.source_manager._parent_manager
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
        sibling: "ParameterFormManager",
    ) -> bool:
        if sibling is context.event.source_manager:
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
        sibling: "ParameterFormManager",
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

    def _refresh_single_field(self, manager: "ParameterFormManager", field_name: str) -> None:
        if DEBUG_DISPATCHER:
            logger.info(f"      🔄 _refresh_single_field: {manager.field_id}.{field_name}")

        if field_name not in manager.widgets:
            if DEBUG_DISPATCHER:
                logger.warning(f"      ⏭️  Field {field_name} not in widgets, skipping")
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




class RootSignalStage:
    """Emits root-manager signals consumed by editor and cross-window listeners."""

    def run(self, context: FieldDispatchContext) -> None:
        logger.debug("🔔 DISPATCHER: Emitting parameter_changed from root")
        logger.debug("  source.field_id=%s", context.event.source_manager.field_id)
        logger.debug("  root.field_id=%s", context.root.field_id)
        logger.debug("  event.field_name=%s", context.event.field_name)
        logger.debug("  full_path=%s", context.event.field.address.value)
        logger.debug("  value type=%s", type(context.event.field.raw).__name__)

        context.root.parameter_changed.emit(context.event.field.address.value, context.event.field.raw)
        logger.debug(
            "  ✅ Emitted parameter_changed(%s, ...) from root",
            context.event.field.address.value,
        )

        self._emit_cross_window(context)

    def _emit_cross_window(self, context: FieldDispatchContext) -> None:
        root_manager = context.root
        full_path = context.event.field.address.value
        logger.debug(
            f"  🔍 _emit_cross_window: checking should_skip_updates() for {root_manager.field_id}"
        )
        logger.debug(
            f"    state._in_reset={root_manager.state._in_reset}, state._block_cross_window_updates={root_manager.state._block_cross_window_updates}"
        )
        if root_manager.state.should_skip_updates():
            logger.warning(
                f"  🚫 Cross-window BLOCKED: _should_skip_updates()=True for {root_manager.field_id}"
            )
            return

        # REMOVED: update_thread_local_global_config() call
        # Thread-local should ONLY be updated on SAVE, not on every keystroke!
        # Descendants (plates, steps) should see the SAVED global config, not unsaved edits.

        logger.debug(
            f"  📡 Emitting context_changed: scope={root_manager.scope_id}, path={full_path}"
        )
        root_manager.context_changed.emit(root_manager.scope_id or "", full_path)
        logger.debug("  ✅ context_changed emitted")


class FieldChangeDispatcher:
    """Singleton coordinator for all field changes."""

    _instance = None

    def __init__(self) -> None:
        self._guard = DispatchReentrancyGuard()
        self._source_state_update = SourceStateUpdateStage()
        self._sibling_placeholder_refresh = SiblingPlaceholderRefreshStage()
        self._live_context_notification = LiveContextNotificationStage()
        self._root_signals = RootSignalStage()

    @classmethod
    def instance(cls) -> "FieldChangeDispatcher":
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
            if self._guard.is_reset_blocked(event):
                return

            logger.debug(
                "🔬 RESET_TRACE: DISPATCHER: is_reset=%s, field=%s, previous=%s",
                event.is_reset,
                event.field_name,
                repr(event.field.raw)[:50],
            )

            context = FieldDispatchContext.for_event(event)
            flash_trace(
                "dispatch.context",
                source=context.event.source_manager.field_id,
                root=context.root.field_id,
                source_path=context.event.field.address.value,
                root_path=context.event.field.address.value,
                reset=context.event.is_reset,
            )
            self._source_state_update.run(context)
            self._sibling_placeholder_refresh.run(context)
            self._live_context_notification.run(context)
            source._enabled_field_styling_service.on_enabled_field_changed(source, event.field)
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
