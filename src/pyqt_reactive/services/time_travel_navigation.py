"""Reopen and focus the editors a completed time-travel restore changed."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from objectstate import ObjectState, ObjectStateRegistry, ScopeKey
from objectstate.time_travel_profile import TimeTravelProfiler
from PyQt6.QtCore import QTimer

from pyqt_reactive.services.function_navigation import (
    FUNCTION_FIELD_ROOT,
    build_function_token_field_path,
    is_function_field_path,
)
from pyqt_reactive.services.scope_window_navigation import ScopeWindowNavigationService
from pyqt_reactive.services.window_navigation import WindowNavigationRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NavigationTarget(ABC):
    """Where in an editor window time travel should focus."""

    value: str

    @property
    @abstractmethod
    def is_function_target(self) -> bool: ...

    @abstractmethod
    def to_field_path(self) -> str: ...

    def replaces(self, existing: NavigationTarget | None) -> bool:
        """Whether this target should replace ``existing`` for the same window.

        A plain field target replaces a function target: undoing a step-level edit
        lands on the step field, not on a function the restore also touched.
        """

        if existing is None:
            return True
        return existing.is_function_target and not self.is_function_target


@dataclass(frozen=True, slots=True)
class FieldPathTarget(NavigationTarget):
    """A dotted field path in the editor's form."""

    @property
    def is_function_target(self) -> bool:
        return is_function_field_path(self.value)

    def to_field_path(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class FunctionTokenTarget(NavigationTarget):
    """One function of the editor's function pattern, by its scope token."""

    @property
    def is_function_target(self) -> bool:
        return True

    def to_field_path(self) -> str:
        return build_function_token_field_path(self.value)


@dataclass(frozen=True, slots=True)
class FunctionScopeRef:
    """A function-pattern child scope and the editor scope that owns it."""

    owner_scope_id: str
    function_token: str


FunctionScopeResolver = Callable[[str], FunctionScopeRef | None]
"""The application's rule for which scopes are function-pattern children."""


@dataclass(frozen=True, slots=True)
class TimeTravelWindowRequest:
    """One editor window to reopen after a restore, and where to focus it."""

    scope_id: str
    object_state: ObjectState
    target: NavigationTarget | None


def dirty_field_sort_key(field: str) -> tuple[int, int, str]:
    """Order dirty fields: the function pattern root first, then deepest paths."""

    return (0 if field == FUNCTION_FIELD_ROOT else 1, -field.count("."), field)


def fallback_field_path(last_changed_field: str | None, dirty_fields: Iterable[str]) -> str | None:
    """The field to focus when no function scope names one."""

    if last_changed_field:
        return last_changed_field
    candidates = [field for field in dirty_fields if isinstance(field, str)]
    return min(candidates, key=dirty_field_sort_key) if candidates else None


@dataclass(frozen=True, slots=True)
class TimeTravelNavigator:
    """Reopens the editors of the scopes a restore changed.

    Only the scope that triggered the restored snapshot (and, for a function
    child, its owning editor) is followed: snapshots capture the whole registry,
    so older dirty states would otherwise reopen unrelated editors.
    ``target_shown`` lets the application adjust a window it navigated to.
    """

    function_scope: FunctionScopeResolver
    target_shown: Callable[[str, NavigationTarget], None] = lambda _scope, _target: None

    def on_time_travel_complete(self, dirty_states, triggering_scope: str | None) -> None:
        """Registry callback: navigate once the restore's own refreshes have run."""

        with TimeTravelProfiler.phase(
            "pyqt_reactive.time_travel.build_window_requests",
            dirty_states=len(dirty_states),
        ):
            pending = self.window_requests(dirty_states, triggering_scope)
        if pending:
            self.defer(lambda: self.navigate(pending, triggering_scope))

    @staticmethod
    def defer(callback: Callable[[], None]) -> None:
        """Run after the refreshes the restore queued in this event-loop turn."""

        QTimer.singleShot(0, lambda: QTimer.singleShot(0, callback))

    def includes(self, changed_scope_id: str, triggering_scope: str | None) -> bool:
        """Whether a changed scope belongs to the edit the restore undid or redid."""

        if triggering_scope is None:
            return True
        triggering_function = self.function_scope(triggering_scope)
        if triggering_function is not None:
            return (
                ScopeKey(triggering_scope).contains(changed_scope_id)
                or changed_scope_id == triggering_function.owner_scope_id
            )
        return changed_scope_id == triggering_scope

    def window_requests(
        self,
        dirty_states,
        triggering_scope: str | None,
    ) -> dict[str, TimeTravelWindowRequest]:
        """Project changed ObjectStates onto one request per editor window."""

        pending: dict[str, TimeTravelWindowRequest] = {}
        for scope_id, state in dirty_states:
            if not self.includes(scope_id, triggering_scope):
                continue
            request = self._request_for(scope_id, state)
            existing = pending.get(request.scope_id)
            if (
                existing is None
                or request.target is not None
                and request.target.replaces(existing.target)
            ):
                pending[request.scope_id] = request
        return pending

    def _request_for(self, scope_id: str, state: ObjectState) -> TimeTravelWindowRequest:
        function_scope = self.function_scope(scope_id)
        if function_scope is not None:
            owner_state = ObjectStateRegistry.get_by_scope(function_scope.owner_scope_id)
            return TimeTravelWindowRequest(
                scope_id=function_scope.owner_scope_id,
                object_state=owner_state if owner_state is not None else state,
                target=FunctionTokenTarget(function_scope.function_token),
            )
        field_path = fallback_field_path(state.last_changed_field, state.dirty_fields)
        return TimeTravelWindowRequest(
            scope_id=scope_id,
            object_state=state,
            target=FieldPathTarget(field_path) if field_path else None,
        )

    def navigate(
        self,
        pending: dict[str, TimeTravelWindowRequest],
        triggering_scope: str | None,
    ) -> None:
        """Open or focus each requested window; create it only for a known edit."""

        for request in pending.values():
            field_path = request.target.to_field_path() if request.target is not None else None
            with TimeTravelProfiler.phase(
                "pyqt_reactive.time_travel.navigate_window",
                scope=request.scope_id,
                field_path=field_path,
            ):
                result = ScopeWindowNavigationService.navigate(
                    WindowNavigationRequest(
                        scope_id=request.scope_id,
                        object_state=request.object_state,
                        field_path=field_path,
                        create_if_missing=triggering_scope is not None,
                    )
                )
            if result.created:
                logger.info("Time travel opened the window for %s", request.scope_id)
            if result.window is not None and request.target is not None:
                self.target_shown(request.scope_id, request.target)

