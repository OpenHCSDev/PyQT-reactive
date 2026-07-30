"""Lifecycle coverage for the generic ZMQ server browser."""

from PyQt6.QtCore import QCoreApplication, QEvent

from pyqt_reactive.theming import ColorScheme, StyleSheetGenerator
from pyqt_reactive.services.zmq_server_scan_service import ZMQServerScanService
from pyqt_reactive.widgets.shared.zmq_server_browser_widget import (
    KillOperationKind,
    KillOperationPlan,
    ServerKillAction,
    ZMQServerBrowserWidgetABC,
)
from zmqruntime import ZMQConfig
from zmqruntime.transport import get_default_transport_mode


class _ScanService:
    def scan_ports(self, _ports):
        return [{"port": 5000}]


class _Browser(ZMQServerBrowserWidgetABC):
    def populate_tree(self, _parsed_servers) -> None:
        pass

    def periodic_domain_cleanup(self) -> None:
        pass

    def kill_ports_with_plan(
        self,
        *,
        ports,
        plan: KillOperationPlan,
        on_server_killed,
    ) -> tuple[bool, str]:
        return True, "done"

    def on_browser_shown(self) -> None:
        pass

    def on_browser_hidden(self) -> None:
        pass

    def on_browser_cleanup(self) -> None:
        pass


def test_scan_service_resolves_omitted_transport_through_transport_owner() -> None:
    scan_service = ZMQServerScanService(config=ZMQConfig(), transport_mode=None)

    assert scan_service.transport_mode is get_default_transport_mode()


def test_scan_completion_is_suppressed_after_cleanup(qapp, monkeypatch) -> None:
    """A scan finishing after cleanup must not emit through a dead widget."""

    callbacks = []
    monkeypatch.setattr(
        "pyqt_reactive.widgets.shared.zmq_server_browser_widget."
        "spawn_thread_with_context",
        lambda callback, *, name: callbacks.append((callback, name)),
    )
    browser = _Browser(
        ports_to_scan=[5000],
        title="Servers",
        style_generator=StyleSheetGenerator(ColorScheme()),
        scan_service=_ScanService(),
    )
    completions = []
    browser._scan_complete.connect(completions.append)

    browser.refresh_servers()
    browser.cleanup()
    callback, name = callbacks.pop()
    callback()

    assert name == "scan_servers"
    assert completions == []
    assert not browser._scan_in_flight
    browser.deleteLater()
    QCoreApplication.sendPostedEvents(browser, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_scan_completion_is_suppressed_after_qt_destroys_browser(
    qapp, monkeypatch
) -> None:
    """QObject destruction must close the lifecycle before a scan completes."""

    callbacks = []
    monkeypatch.setattr(
        "pyqt_reactive.widgets.shared.zmq_server_browser_widget."
        "spawn_thread_with_context",
        lambda callback, *, name: callbacks.append((callback, name)),
    )
    browser = _Browser(
        ports_to_scan=[5000],
        title="Servers",
        style_generator=StyleSheetGenerator(ColorScheme()),
        scan_service=_ScanService(),
    )
    completions = []
    browser._scan_complete.connect(completions.append)

    browser.refresh_servers()
    lifecycle = browser._lifecycle_state
    browser.deleteLater()
    QCoreApplication.sendPostedEvents(browser, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    callback, name = callbacks.pop()
    callback()

    assert name == "scan_servers"
    assert lifecycle.is_cleaning_up()
    assert completions == []


def test_browser_owns_periodic_timers(qapp) -> None:
    """Qt destruction must also destroy the browser's periodic timers."""

    browser = _Browser(
        ports_to_scan=[5000],
        title="Servers",
        style_generator=StyleSheetGenerator(ColorScheme()),
        scan_service=_ScanService(),
    )

    assert browser.refresh_timer.parent() is browser
    assert browser._cleanup_timer.parent() is browser

    browser.deleteLater()
    QCoreApplication.sendPostedEvents(browser, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_kill_completion_is_suppressed_after_cleanup(qapp, monkeypatch) -> None:
    """A kill finishing after cleanup must not emit through a dead widget."""

    callbacks = []
    monkeypatch.setattr(
        "pyqt_reactive.widgets.shared.zmq_server_browser_widget."
        "spawn_thread_with_context",
        lambda callback, *, name: callbacks.append((callback, name)),
    )
    browser = _Browser(
        ports_to_scan=[5000],
        title="Servers",
        style_generator=StyleSheetGenerator(ColorScheme()),
        scan_service=_ScanService(),
    )
    completions = []
    killed_ports = []
    browser._kill_complete.connect(
        lambda success, message: completions.append((success, message))
    )
    browser.server_killed.connect(killed_ports.append)
    browser.kill_ports_with_plan = lambda *, ports, plan, on_server_killed: (
        on_server_killed(ports[0]) or (True, "done")
    )

    action = ServerKillAction.from_kind([5000], KillOperationKind.GRACEFUL)
    browser._spawn_server_kill_thread(action)
    browser.cleanup()
    callback, name = callbacks.pop()
    callback()

    assert name == action.thread_name
    assert completions == []
    assert killed_ports == []
    browser.deleteLater()
    QCoreApplication.sendPostedEvents(browser, QEvent.Type.DeferredDelete)
    qapp.processEvents()
