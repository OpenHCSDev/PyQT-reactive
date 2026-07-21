"""Lifecycle coverage for the generic ZMQ server browser."""

from PyQt6.QtCore import QCoreApplication, QEvent

from pyqt_reactive.theming import ColorScheme, StyleSheetGenerator
from pyqt_reactive.widgets.shared.zmq_server_browser_widget import (
    KillOperationPlan,
    ZMQServerBrowserWidgetABC,
)


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
