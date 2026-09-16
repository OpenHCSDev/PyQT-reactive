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


def test_list_driver_accepts_only_present_identity_and_preserves_dispatch(qapp) -> None:
    from PyQt6.QtWidgets import QWidget

    from pyqt_reactive.services.window_manager import WindowManager
    from pyqt_reactive.services.window_navigation import ListItemWindowNavigationDriver

    window = QWidget()
    items = {"first", "second"}
    selected = []
    driver = ListItemWindowNavigationDriver(
        selected.append, lambda: bool(items), items.__contains__
    )
    WindowManager.register("list", window, navigation_driver=driver)
    try:
        for item_id, field_path, accepted in (
            ("second", None, True),
            ("absent", None, False),
            ("first", "field", False),
            (None, "field", False),
        ):
            result = WindowManager.focus_and_navigate_result(
                "list", item_id=item_id, field_path=field_path
            )
            qapp.processEvents()
            assert result.focused
            assert result.navigated is accepted
        assert selected == ["second"]
        items.clear()
        result = WindowManager.focus_and_navigate_result("list", item_id="second")
        qapp.processEvents()
        assert not result.navigated
        assert selected == ["second"]

        items.add("first")
        result = WindowManager.focus_and_navigate_result("list", item_id="first")
        assert result.navigated  # The original target was accepted.
        items.remove("first")  # The list changes before deferred Qt dispatch.
        qapp.processEvents()
        assert selected == ["second"]  # Stale navigation is cancelled.
    finally:
        WindowManager.unregister("list", window)
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


def test_terminal_navigation_distinguishes_execution_from_unknown_exposure(qtbot):
    from PyQt6.QtWidgets import QWidget
    from pyqt_reactive.services.window_manager import WindowManager
    from pyqt_reactive.services.window_navigation import ListItemWindowNavigationDriver

    window = QWidget()
    qtbot.addWidget(window)
    selected, completed = [], []
    dispatch = WindowManager.dispatch_widget_navigation(
        window, ListItemWindowNavigationDriver(selected.append, lambda: True,
                                                lambda identity: identity == "item"),
        requested_scope_id="list-terminal", item_id="item", completed=completed.append,
    )
    assert dispatch.target_accepted
    assert not completed
    qtbot.waitUntil(lambda: bool(completed))
    assert selected == ["item"]
    assert completed[0].executed
    assert completed[0].target_exposed is None


def test_terminal_navigation_reports_exhausted_readiness(qtbot):
    from PyQt6.QtWidgets import QWidget
    from pyqt_reactive.services.window_manager import WindowManager
    from pyqt_reactive.services.window_navigation import (
        FieldWindowNavigationDriver, NavigationWaitReason, RegisteredWindowNavigationReadiness,
    )

    class WaitingDriver(FieldWindowNavigationDriver):
        def readiness(self, request):
            return RegisteredWindowNavigationReadiness(wait_reason=NavigationWaitReason.LAYOUT)

    window = QWidget()
    qtbot.addWidget(window)
    completed, selected = [], []
    WindowManager.dispatch_widget_navigation(
        window, WaitingDriver(selected.append), requested_scope_id="never-ready",
        field_path="value", completed=completed.append,
    )
    qtbot.waitUntil(lambda: bool(completed), timeout=1500)
    assert not selected
    assert not completed[0].executed
    assert completed[0].wait_reason is NavigationWaitReason.LAYOUT


def test_terminal_navigation_reports_destroyed_window_once(qapp, qtbot):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QWidget
    from pyqt_reactive.services.window_manager import WindowManager
    from pyqt_reactive.services.window_navigation import FieldWindowNavigationDriver

    window = QWidget()
    selected, completed = [], []
    WindowManager.dispatch_widget_navigation(
        window, FieldWindowNavigationDriver(selected.append), requested_scope_id="destroyed",
        field_path="value", completed=completed.append,
    )
    window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qtbot.waitUntil(lambda: bool(completed))
    assert not selected
    assert len(completed) == 1
    assert not completed[0].window_alive


def test_scrollable_terminal_exposure_uses_actual_target_viewport(qtbot):
    from PyQt6.QtWidgets import QWidget, QScrollArea, QVBoxLayout, QLabel
    from pyqt_reactive.services.window_manager import WindowManager
    from pyqt_reactive.services.window_navigation import RegisteredWindowNavigationReadiness
    from pyqt_reactive.widgets.shared.scrollable_form_mixin import (
        ScrollableFormMixin, ScrollableFormWindowNavigationDriver, ScrollTarget,
    )

    class Owner(QWidget, ScrollableFormMixin):
        def __init__(self):
            super().__init__()
            self.resize(300, 180)
            self.scroll_area = QScrollArea(self)
            self.scroll_area.setWidgetResizable(True)
            QVBoxLayout(self).addWidget(self.scroll_area)
            content = QWidget()
            layout = QVBoxLayout(content)
            for index in range(30):
                label = QLabel(f"Field {index}")
                label.setMinimumHeight(30)
                layout.addWidget(label)
            self.leaf = label
            self.scroll_area.setWidget(content)

        def _resolve_navigation_scroll_target(self, field_path):
            return ScrollTarget(field_path, "leaf", "", self.leaf, None, None, True), False

        def select_and_scroll_to_field(self, field_path):
            self._scroll_to_section(field_path, flash=False)

    class Driver(ScrollableFormWindowNavigationDriver):
        def accepts_field_path(self, request):
            return request.field_path == "leaf"

        def readiness(self, request):
            # This fixture has an already-built native layout; the production
            # owner's viewport/exposure behavior remains unchanged.
            return RegisteredWindowNavigationReadiness()

    owner = Owner()
    qtbot.addWidget(owner)
    owner.show()
    qtbot.waitExposed(owner)
    driver = Driver(owner)
    completed = []
    WindowManager.dispatch_widget_navigation(
        owner, driver, requested_scope_id="scrollable", field_path="leaf",
        completed=completed.append,
    )
    assert not completed
    qtbot.waitUntil(lambda: bool(completed))
    assert completed[0].executed
    assert completed[0].target_exposed is True
    assert owner.scroll_area.verticalScrollBar().value() > 0
