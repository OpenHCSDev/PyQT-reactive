"""Nominal window-navigation capabilities used by pyqt-reactive services."""

from __future__ import annotations

from abc import ABC
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from objectstate import ObjectState
from PyQt6.QtWidgets import QWidget


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

    @property
    def navigated(self) -> bool:
        return self.focused and self.request.has_target


class NavigationWaitReason(Enum):
    FORM_MANAGER = "form manager"
    ROOT_WIDGETS = "root widgets"
    NESTED_MANAGER = "nested manager"
    FIELD_TARGET = "field target"
    LAYOUT = "layout"
    LIST_ITEMS = "list items"


@dataclass(frozen=True, slots=True)
class RegisteredWindowNavigationRequest:
    """Navigation request after a WindowManager scope resolved to a widget."""

    window: QWidget
    item_id: str | None = None
    field_path: str | None = None

    @property
    def has_target(self) -> bool:
        return self.item_id is not None or self.field_path is not None


@dataclass(frozen=True, slots=True)
class RegisteredWindowNavigationReadiness:
    """Readiness result from a registered window navigation driver."""

    window_alive: bool = True
    wait_reason: NavigationWaitReason | None = None

    @property
    def needs_wait(self) -> bool:
        return self.wait_reason is not None


class WindowNavigationDriver(ABC):
    """Registered navigation behavior for one WindowManager scope."""

    def readiness(
        self,
        request: RegisteredWindowNavigationRequest,
    ) -> RegisteredWindowNavigationReadiness:
        del request
        return RegisteredWindowNavigationReadiness()

    def build_complete_callbacks(self) -> tuple[list[Callable[[], None]], ...]:
        return ()

    def execute(self, request: RegisteredWindowNavigationRequest) -> None:
        del request


class NullWindowNavigationDriver(WindowNavigationDriver):
    """No-op navigation driver for windows without navigation behavior."""


class CompositeWindowNavigationDriver(WindowNavigationDriver):
    """Combine independent navigation drivers declared by one window."""

    def __init__(self, drivers: tuple[WindowNavigationDriver, ...]) -> None:
        self._drivers = drivers

    def readiness(
        self,
        request: RegisteredWindowNavigationRequest,
    ) -> RegisteredWindowNavigationReadiness:
        for driver in self._drivers:
            readiness = driver.readiness(request)
            if not readiness.window_alive or readiness.needs_wait:
                return readiness
        return RegisteredWindowNavigationReadiness()

    def build_complete_callbacks(self) -> tuple[list[Callable[[], None]], ...]:
        callback_lists: list[list[Callable[[], None]]] = []
        for driver in self._drivers:
            callback_lists.extend(driver.build_complete_callbacks())
        return tuple(callback_lists)

    def execute(self, request: RegisteredWindowNavigationRequest) -> None:
        for driver in self._drivers:
            driver.execute(request)


class FieldWindowNavigationDriver(WindowNavigationDriver):
    """Navigate field paths through an explicit field-scrolling callable."""

    def __init__(self, select_field: Callable[[str], None]) -> None:
        self._select_field = select_field

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
        form_manager: Callable[[], FormNavigationManager | None],
    ) -> None:
        super().__init__(select_field)
        self._form_manager = form_manager

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
        if "." in request.field_path and not self._nested_manager_exists(
            form_manager,
            request.field_path,
        ):
            return RegisteredWindowNavigationReadiness(
                wait_reason=NavigationWaitReason.NESTED_MANAGER,
            )
        return RegisteredWindowNavigationReadiness()

    def build_complete_callbacks(self) -> tuple[list[Callable[[], None]], ...]:
        form_manager = self._form_manager()
        if form_manager is None:
            return ()
        return (form_manager._on_build_complete_callbacks,)

    @staticmethod
    def _nested_manager_exists(
        form_manager: FormNavigationManager,
        field_path: str,
    ) -> bool:
        current_manager = form_manager
        path_parts = field_path.split(".")

        for part in path_parts[:-1]:
            if part not in current_manager.nested_managers:
                return FormFieldWindowNavigationDriver._is_inline_dataclass_field(
                    current_manager,
                    part,
                )
            current_manager = current_manager.nested_managers[part]

        return True

    @staticmethod
    def _is_inline_dataclass_field(
        form_manager: FormNavigationManager,
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
    ) -> None:
        self._select_item = select_item
        self._has_navigation_items = has_navigation_items

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
        if request.item_id is None:
            return
        self._select_item(request.item_id)


class FormNavigationManager(ABC):
    """Form manager surface needed for deferred field navigation."""

    widgets: dict
    nested_managers: dict
    _on_build_complete_callbacks: list
