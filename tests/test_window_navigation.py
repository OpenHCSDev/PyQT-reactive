"""Navigation ownership and truthful dispatch contracts."""

from __future__ import annotations


def test_scope_route_preserves_requested_scope_for_registered_driver(qapp) -> None:
    from PyQt6.QtWidgets import QWidget

    from pyqt_reactive.services.scope_window_factory import ScopeWindowRegistry
    from pyqt_reactive.services.scope_window_navigation import (
        ScopeWindowNavigationService,
    )
    from pyqt_reactive.services.window_manager import WindowManager
    from pyqt_reactive.services.window_navigation import (
        FieldWindowNavigationDriver,
        RegisteredWindowNavigationRequest,
        WindowNavigationRequest,
    )

    prepared_scopes: list[str] = []
    selected_fields: list[str] = []

    class CapturingFieldDriver(FieldWindowNavigationDriver):
        def prepare(self, request: RegisteredWindowNavigationRequest) -> None:
            prepared_scopes.append(request.requested_scope_id)

    window = QWidget()
    driver = CapturingFieldDriver(selected_fields.append)
    WindowManager.register("shared_window", window, navigation_driver=driver)
    ScopeWindowRegistry.register_handler(
        pattern=r"^declared_scope$",
        window_scope_resolver=lambda _scope_id: "shared_window",
    )

    try:
        result = ScopeWindowNavigationService.navigate(
            WindowNavigationRequest(
                scope_id="declared_scope",
                field_path="nested.value",
            )
        )
        qapp.processEvents()

        assert result.focused
        assert result.target_accepted
        assert result.navigated
        assert prepared_scopes == ["declared_scope"]
        assert selected_fields == ["nested.value"]
    finally:
        WindowManager.unregister("shared_window", window)
        ScopeWindowRegistry.clear()
        window.close()


def test_null_driver_focuses_without_claiming_target_navigation(qapp) -> None:
    from PyQt6.QtWidgets import QWidget

    from pyqt_reactive.services.window_manager import WindowManager

    window = QWidget()
    WindowManager.register("focus_only", window)

    try:
        dispatch = WindowManager.focus_and_navigate_result(
            "focus_only",
            field_path="unknown",
        )
        qapp.processEvents()

        assert dispatch.focused
        assert dispatch.target_requested
        assert not dispatch.target_accepted
        assert not dispatch.navigated
    finally:
        WindowManager.unregister("focus_only", window)
        window.close()


def test_build_owned_readiness_does_not_spend_poll_retry_budget(qapp) -> None:
    from PyQt6.QtWidgets import QWidget

    from pyqt_reactive.services.window_manager import NavigationRetryScheduler
    from pyqt_reactive.services.window_navigation import (
        RegisteredWindowNavigationRequest,
        WindowNavigationDriver,
    )

    class BuildOwnedDriver(WindowNavigationDriver):
        def __init__(self) -> None:
            self.callbacks = []

        def register_readiness_callback(self, request, callback):
            del request
            self.callbacks.append(callback)
            return True

    window = QWidget()
    request = RegisteredWindowNavigationRequest(
        window=window,
        requested_scope_id="building_form",
        field_path="nested.value",
    )
    driver = BuildOwnedDriver()
    retry_counts = {id(request): 4}

    try:
        assert NavigationRetryScheduler.schedule(
            request,
            driver,
            retry_counts,
            lambda: None,
        )
        assert retry_counts == {}
        assert len(driver.callbacks) == 1
    finally:
        window.close()


def test_composite_dispatches_only_to_matching_nominal_driver(qapp) -> None:
    from PyQt6.QtWidgets import QWidget

    from pyqt_reactive.services.window_navigation import (
        CompositeWindowNavigationDriver,
        RegisteredWindowNavigationReadiness,
        RegisteredWindowNavigationRequest,
        WindowNavigationDriver,
    )

    class SelectiveFieldDriver(WindowNavigationDriver):
        def __init__(self, owned_field: str) -> None:
            self.owned_field = owned_field
            self.calls: list[str] = []

        def accepts_field_path(self, request) -> bool:
            return request.field_path == self.owned_field

        def prepare(self, request) -> None:
            del request
            self.calls.append("prepare")

        def readiness(self, request):
            del request
            self.calls.append("readiness")
            return RegisteredWindowNavigationReadiness()

        def register_readiness_callback(self, request, callback) -> bool:
            del request, callback
            self.calls.append("register")
            return False

        def execute(self, request) -> None:
            del request
            self.calls.append("execute")

    window = QWidget()
    matching = SelectiveFieldDriver("owned.value")
    unrelated = SelectiveFieldDriver("other.value")
    driver = CompositeWindowNavigationDriver((matching, unrelated))
    request = RegisteredWindowNavigationRequest(
        window=window,
        requested_scope_id="composite",
        field_path="owned.value",
    )

    try:
        assert driver.accepts(request)
        driver.prepare(request)
        assert not driver.readiness(request).needs_wait
        assert not driver.register_readiness_callback(request, lambda: None)
        driver.execute(request)

        assert matching.calls == ["prepare", "readiness", "register", "execute"]
        assert unrelated.calls == []
    finally:
        window.close()
