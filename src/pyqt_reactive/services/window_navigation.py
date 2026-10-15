"""Nominal window-navigation capabilities used by pyqt-reactive services."""

from __future__ import annotations

from abc import ABC
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, TypeVar

from objectstate import DottedFieldPath, ObjectState
from PyQt6.QtWidgets import QWidget

if TYPE_CHECKING:
    from pyqt_reactive.forms.widget_creation_types import ParameterFormManager

OwnerT = TypeVar("OwnerT")


@dataclass(frozen=True, slots=True)
class WindowNavigationRequest:
    """Typed request to focus a scope window and reveal an item or field."""

    scope_id: str
    object_state: ObjectState | None = None
    item_id: str | None = None
    field_path: str | None = None
    create_if_missing: bool = True
    avoid_widgets: tuple[QWidget, ...] = ()

    @property
    def has_target(self) -> bool:
        return self.item_id is not None or self.field_path is not None


@dataclass(frozen=True, slots=True)
class WindowNavigationResult:
    """Outcome of one scope-window navigation request."""

    request: WindowNavigationRequest
    window: QWidget | None
    focused: bool
    created: bool
    window_scope_id: str | None = None
    target_accepted: bool = False

    @property
    def navigated(self) -> bool:
        return self.focused and self.request.has_target and self.target_accepted


class NavigationWaitReason(Enum):
    FORM_MANAGER = "form manager"
    ROOT_WIDGETS = "root widgets"
    NESTED_MANAGER = "nested manager"
    FIELD_TARGET = "field target"
    LAYOUT = "layout"
    LIST_ITEMS = "list items"


class NavigationTargetClaimedTwiceError(LookupError):
    """Several owners in one window claim the same navigation target."""


def sole_owner(claimants: Sequence[OwnerT], target: str) -> OwnerT | None:
    """The one owner of a navigation target, or ``None`` when nobody claims it.

    This is the only place that says what happens when owners overlap. Each
    owner (a tab, a form, an editor) claims the field paths it shows, from its
    own declared fields. The owners of one window partition its targets, so two
    claims on one target are a declaration error: this raises and names the
    claimants. Nothing picks a winner by position.
    """

    if len(claimants) > 1:
        raise NavigationTargetClaimedTwiceError(
            f"{target} is claimed by {len(claimants)} owners: "
            + ", ".join(repr(claimant) for claimant in claimants)
            + ". Each owner must claim only the fields it shows."
        )
    return claimants[0] if claimants else None


@dataclass(frozen=True, slots=True)
class RegisteredWindowNavigationRequest:
    """Navigation request after a WindowManager scope resolved to a widget."""

    window: QWidget
    requested_scope_id: str
    item_id: str | None = None
    field_path: str | None = None

    @property
    def has_target(self) -> bool:
        return self.item_id is not None or self.field_path is not None


@dataclass(frozen=True, slots=True)
class WindowNavigationDispatch:
    """Immediate dispatch result before deferred UI navigation completes."""

    focused: bool
    target_requested: bool
    target_accepted: bool

    @property
    def navigated(self) -> bool:
        return self.focused and self.target_requested and self.target_accepted


@dataclass(frozen=True, slots=True)
class RegisteredWindowNavigationReadiness:
    """Readiness result from a registered window navigation driver."""

    window_alive: bool = True
    wait_reason: NavigationWaitReason | None = None

    @property
    def needs_wait(self) -> bool:
        return self.wait_reason is not None


@dataclass(frozen=True, slots=True)
class RegisteredWindowNavigationCompletion:
    """Terminal facts from the existing deferred navigation lifecycle.

    Unknown exposure does not erase successful execution. Capture consumers
    require positive exposure, rather than mistaking accepted dispatch for it.
    """

    executed: bool
    target_exposed: bool | None = None
    window_alive: bool = True
    wait_reason: NavigationWaitReason | None = None
    error: Exception | None = None


class WindowNavigationDriver(ABC):
    """Registered navigation behavior for one WindowManager scope."""

    def accepts(self, request: RegisteredWindowNavigationRequest) -> bool:
        """Return whether this driver owns every target carried by ``request``."""

        return (
            request.has_target
            and (request.field_path is None or self.accepts_field_path(request))
            and (request.item_id is None or self.accepts_item_id(request))
        )

    def accepts_field_path(
        self,
        request: RegisteredWindowNavigationRequest,
    ) -> bool:
        del request
        return False

    def accepts_item_id(
        self,
        request: RegisteredWindowNavigationRequest,
    ) -> bool:
        del request
        return False

    def prepare(self, request: RegisteredWindowNavigationRequest) -> None:
        """Prepare the owning view before asynchronous readiness checks."""

        del request

    def readiness(
        self,
        request: RegisteredWindowNavigationRequest,
    ) -> RegisteredWindowNavigationReadiness:
        del request
        return RegisteredWindowNavigationReadiness()

    def register_readiness_callback(
        self,
        request: RegisteredWindowNavigationRequest,
        callback: Callable[[], None],
    ) -> bool:
        del request
        del callback
        return False

    def execute(self, request: RegisteredWindowNavigationRequest) -> None:
        del request

    def target_exposed(self, request: RegisteredWindowNavigationRequest) -> bool | None:
        """Return proved target exposure, or unknown for unsupported owners."""
        del request
        return None


class NullWindowNavigationDriver(WindowNavigationDriver):
    """No-op navigation driver for windows without navigation behavior."""


class CompositeWindowNavigationDriver(WindowNavigationDriver):
    """Navigate through whichever of one window's drivers owns the target.

    Every driver says what it accepts in its own terms. A field path or an
    item has at most one owner among them (:func:`sole_owner`).
    """

    def __init__(self, drivers: tuple[WindowNavigationDriver, ...]) -> None:
        self._drivers = drivers

    def accepts_field_path(
        self,
        request: RegisteredWindowNavigationRequest,
    ) -> bool:
        return self._field_path_owner(request) is not None

    def accepts_item_id(
        self,
        request: RegisteredWindowNavigationRequest,
    ) -> bool:
        return self._item_owner(request) is not None

    def _field_path_owner(
        self,
        request: RegisteredWindowNavigationRequest,
    ) -> WindowNavigationDriver | None:
        if request.field_path is None:
            return None
        return sole_owner(
            tuple(driver for driver in self._drivers if driver.accepts_field_path(request)),
            f"Field path {request.field_path!r}",
        )

    def _item_owner(
        self,
        request: RegisteredWindowNavigationRequest,
    ) -> WindowNavigationDriver | None:
        if request.item_id is None:
            return None
        return sole_owner(
            tuple(driver for driver in self._drivers if driver.accepts_item_id(request)),
            f"Item {request.item_id!r}",
        )

    def prepare(self, request: RegisteredWindowNavigationRequest) -> None:
        for driver in self._matching_drivers(request):
            driver.prepare(request)

    def readiness(
        self,
        request: RegisteredWindowNavigationRequest,
    ) -> RegisteredWindowNavigationReadiness:
        for driver in self._matching_drivers(request):
            readiness = driver.readiness(request)
            if not readiness.window_alive or readiness.needs_wait:
                return readiness
        return RegisteredWindowNavigationReadiness()

    def register_readiness_callback(
        self,
        request: RegisteredWindowNavigationRequest,
        callback: Callable[[], None],
    ) -> bool:
        registered = False
        for driver in self._matching_drivers(request):
            if driver.register_readiness_callback(request, callback):
                registered = True
        return registered

    def execute(self, request: RegisteredWindowNavigationRequest) -> None:
        for driver in self._matching_drivers(request):
            driver.execute(request)

    def target_exposed(self, request: RegisteredWindowNavigationRequest) -> bool | None:
        exposures = tuple(driver.target_exposed(request)
                          for driver in self._matching_drivers(request))
        if not exposures or any(exposure is None for exposure in exposures):
            return None
        return all(exposures)

    def _matching_drivers(
        self,
        request: RegisteredWindowNavigationRequest,
    ) -> tuple[WindowNavigationDriver, ...]:
        """The owner of the request's field path and the owner of its item."""
        owners = (self._field_path_owner(request), self._item_owner(request))
        return tuple(
            driver
            for index, driver in enumerate(owners)
            if driver is not None and driver not in owners[:index]
        )


class FieldWindowNavigationDriver(WindowNavigationDriver):
    """Navigate to the field paths of one thing that shows fields.

    The driver holds no field list. ``owns_field_path`` and ``select_field``
    are that thing's own answers: whether a path is one of the fields it
    shows, and how to reveal it.
    """

    def __init__(
        self,
        select_field: Callable[[str], None],
        owns_field_path: Callable[[str], bool],
    ) -> None:
        self._select_field = select_field
        self._owns_field_path = owns_field_path

    def accepts_field_path(
        self,
        request: RegisteredWindowNavigationRequest,
    ) -> bool:
        return request.field_path is not None and self._owns_field_path(request.field_path)

    def execute(self, request: RegisteredWindowNavigationRequest) -> None:
        if request.field_path is None:
            return

        from pyqt_reactive.animation import WindowFlashOverlay

        WindowFlashOverlay.get_for_window(request.window)
        self._select_field(request.field_path)


class FormFieldWindowNavigationDriver(FieldWindowNavigationDriver):
    """Field navigation driver that can report async form-build readiness."""

    def __init__(
        self,
        select_field: Callable[[str], None],
        form_manager: Callable[[], ParameterFormManager | None],
    ) -> None:
        super().__init__(select_field, self._form_owns_field_path)
        self._form_manager = form_manager

    def _form_owns_field_path(self, field_path: str) -> bool:
        """Ask the form. Until it exists the target is accepted, and readiness waits for it."""
        form_manager = self._form_manager()
        if form_manager is None:
            return True
        return form_manager.owns_field_path(field_path)

    def readiness(
        self,
        request: RegisteredWindowNavigationRequest,
    ) -> RegisteredWindowNavigationReadiness:
        if request.field_path is None:
            return RegisteredWindowNavigationReadiness()

        form_manager = self._form_manager()
        if form_manager is None:
            return RegisteredWindowNavigationReadiness(
                wait_reason=NavigationWaitReason.FORM_MANAGER,
            )
        if len(form_manager.widgets) == 0:
            return RegisteredWindowNavigationReadiness(
                wait_reason=NavigationWaitReason.ROOT_WIDGETS,
            )
        if DottedFieldPath(request.field_path).parent.value and not self._nested_manager_exists(
            form_manager,
            request.field_path,
        ):
            return RegisteredWindowNavigationReadiness(
                wait_reason=NavigationWaitReason.NESTED_MANAGER,
            )
        return RegisteredWindowNavigationReadiness()

    def register_readiness_callback(
        self,
        request: RegisteredWindowNavigationRequest,
        callback: Callable[[], None],
    ) -> bool:
        form_manager = self._form_manager()
        if form_manager is None:
            return False
        return form_manager.register_form_build_completion_callback(callback)

    @staticmethod
    def _nested_manager_exists(
        form_manager: ParameterFormManager,
        field_path: str,
    ) -> bool:
        current_manager = form_manager
        for part in DottedFieldPath(field_path).parent.parts:
            if part not in current_manager.nested_managers:
                return FormFieldWindowNavigationDriver._is_inline_dataclass_field(
                    current_manager,
                    part,
                )
            current_manager = current_manager.nested_managers[part]

        return True

    @staticmethod
    def _is_inline_dataclass_field(
        form_manager: ParameterFormManager,
        field_name: str,
    ) -> bool:
        from pyqt_reactive.widgets.shared.clickable_help_components import (
            InlineDataclassGroupBox,
        )

        return isinstance(
            form_manager.widgets.get(field_name),
            InlineDataclassGroupBox,
        )


class ListItemWindowNavigationDriver(WindowNavigationDriver):
    """Navigate list items through explicit item-selection/readiness callables."""

    def __init__(
        self,
        select_item: Callable[[str], None],
        has_navigation_items: Callable[[], bool],
        contains_item: Callable[[str], bool],
    ) -> None:
        self._select_item = select_item
        self._has_navigation_items = has_navigation_items
        self._contains_item = contains_item

    def accepts_item_id(
        self,
        request: RegisteredWindowNavigationRequest,
    ) -> bool:
        return request.item_id is not None and self._contains_item(request.item_id)

    def readiness(
        self,
        request: RegisteredWindowNavigationRequest,
    ) -> RegisteredWindowNavigationReadiness:
        if request.item_id is None:
            return RegisteredWindowNavigationReadiness()
        if self._has_navigation_items():
            return RegisteredWindowNavigationReadiness()
        return RegisteredWindowNavigationReadiness(
            wait_reason=NavigationWaitReason.LIST_ITEMS,
        )

    def execute(self, request: RegisteredWindowNavigationRequest) -> None:
        if not self.accepts_item_id(request):
            return
        self._select_item(request.item_id)
