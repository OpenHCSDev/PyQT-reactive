"""Lifecycle coverage for the generic ZMQ server browser."""

from PyQt6.QtCore import QCoreApplication, QEvent
from zmqruntime import (
    EndpointShutdownMode,
    EndpointShutdownResult,
    TransportMode,
    ZMQConfig,
)
from zmqruntime.messages import PongResponse, ProcessIdentity, ServerRole
from zmqruntime.shutdown import (
    EndpointShutdownBatchResult,
    EndpointShutdownOutcome,
    EndpointShutdownService,
)
from zmqruntime.startup import EndpointStartupPhase, EndpointStartupStatus
from zmqruntime.transport import TransportEndpoint, get_default_transport_mode

from pyqt_reactive.services.zmq_server_scan_service import (
    EndpointObservationAuthority,
    EndpointObservationSnapshot,
    EndpointScanResult,
    ZMQServerScanService,
)
from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.shared.zmq_server_browser_widget import (
    ZMQServerBrowserWidgetABC,
)


class _ScanService:
    config = ZMQConfig()

    def scan_ports(self, _ports, *, previous_snapshot=None):
        del previous_snapshot
        return EndpointObservationSnapshot()

    def endpoint(self, port: int) -> TransportEndpoint:
        return TransportEndpoint(
            host="localhost",
            port=port,
            transport_mode=get_default_transport_mode(),
        )


class _SequencedScanService(_ScanService):
    def __init__(self, snapshots):
        self._snapshots = iter(snapshots)
        self.previous_snapshots = []

    def scan_ports(self, _ports, *, previous_snapshot=None):
        self.previous_snapshots.append(previous_snapshot)
        return next(self._snapshots)


class _Browser(ZMQServerBrowserWidgetABC):
    def populate_tree(self, _parsed_servers) -> None:
        pass

    def periodic_domain_cleanup(self) -> None:
        pass

    def on_browser_shown(self) -> None:
        pass

    def on_browser_hidden(self) -> None:
        pass

    def on_browser_cleanup(self) -> None:
        pass


def test_scan_service_resolves_omitted_transport_through_transport_owner() -> None:
    scan_service = ZMQServerScanService(config=ZMQConfig(), transport_mode=None)

    assert scan_service.transport_mode is get_default_transport_mode()


def test_endpoint_snapshot_is_the_authority_for_tree_and_status(qapp) -> None:
    browser = _Browser(
        ports_to_scan=[5000],
        title="Servers",
        color_scheme=ColorScheme(),
        scan_service=_ScanService(),
    )
    snapshot = EndpointObservationSnapshot.from_responses(
        (
            PongResponse(
                port=5000,
                control_port=6000,
                ready=True,
                server="ExecutionServer",
                server_role=ServerRole.EXECUTION,
                process_identity=ProcessIdentity.current(),
            ),
        )
    )
    published = []
    browser.endpoint_snapshot_changed.connect(published.append)

    browser._update_server_list(
        EndpointScanResult(
            snapshot=snapshot,
            base_authority=browser._endpoint_authority,
        )
    )

    assert browser._endpoint_snapshot is snapshot
    assert published == [snapshot]
    assert snapshot.status_for_port(5000).phase is EndpointStartupPhase.CONNECTED
    assert snapshot.status_for_port(5001).phase is EndpointStartupPhase.DISCONNECTED

    retained = EndpointObservationSnapshot().retain_proven_live_from(
        snapshot,
        lambda response: response.process_identity.is_alive() is True,
    )
    assert retained == snapshot

    dropped = EndpointObservationSnapshot().retain_proven_live_from(
        snapshot,
        lambda _response: False,
    )
    assert dropped.responses == ()

    browser.deleteLater()
    QCoreApplication.sendPostedEvents(browser, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_snapshot_removal_publishes_the_exact_terminated_endpoint(qapp) -> None:
    scan_service = _ScanService()
    browser = _Browser(
        ports_to_scan=[5000],
        title="Servers",
        color_scheme=ColorScheme(),
        scan_service=scan_service,
    )
    observed = []
    browser.endpoint_terminated.connect(observed.append)
    browser._commit_endpoint_snapshot(
        EndpointObservationSnapshot.from_responses(
            (
                PongResponse(
                    port=5000,
                    control_port=6000,
                    ready=True,
                    server="ExecutionServer",
                    server_role=ServerRole.EXECUTION,
                ),
            )
        )
    )

    browser._commit_endpoint_snapshot(EndpointObservationSnapshot())

    assert observed == [scan_service.endpoint(5000)]


def test_scan_result_from_replaced_service_cannot_commit(qapp) -> None:
    old_scan_service = _ScanService()
    browser = _Browser(
        ports_to_scan=[5000],
        title="Servers",
        color_scheme=ColorScheme(),
        scan_service=old_scan_service,
    )
    stale_snapshot = EndpointObservationSnapshot.from_responses(
        (
            PongResponse(
                port=5000,
                control_port=6000,
                ready=True,
                server="OldServer",
                server_role=ServerRole.GENERIC,
            ),
        )
    )
    old_authority = browser._endpoint_authority
    browser._scan_requests.request()
    browser._endpoint_authority = EndpointObservationAuthority(_ScanService(), (5000,))
    follow_up_scans = []
    browser._start_server_scan = lambda: follow_up_scans.append(True)

    browser._update_server_list(
        EndpointScanResult(
            snapshot=stale_snapshot,
            base_authority=old_authority,
        )
    )

    assert browser._endpoint_snapshot == EndpointObservationSnapshot()
    assert follow_up_scans == [True]


def test_replacing_scan_declaration_immediately_invalidates_previous_rows(
    qapp,
    monkeypatch,
) -> None:
    original = ZMQServerScanService(
        config=ZMQConfig(),
        host="127.0.0.1",
        transport_mode=TransportMode.TCP,
    )
    browser = _Browser(
        ports_to_scan=[5000],
        title="Servers",
        color_scheme=ColorScheme(),
        scan_service=original,
    )
    browser._commit_endpoint_snapshot(
        EndpointObservationSnapshot.from_responses(
            (
                PongResponse(
                    port=5000,
                    control_port=6000,
                    ready=True,
                    server="OldServer",
                    server_role=ServerRole.GENERIC,
                ),
            )
        )
    )
    replacement = ZMQServerScanService(
        config=ZMQConfig(),
        host="127.0.0.2",
        transport_mode=TransportMode.TCP,
    )
    refreshes: list[bool] = []
    terminated: list[TransportEndpoint] = []
    browser.endpoint_terminated.connect(terminated.append)
    monkeypatch.setattr(
        browser,
        "refresh_servers",
        lambda: refreshes.append(True),
    )

    browser.replace_scan_declaration(
        scan_service=replacement,
        ports_to_scan=[7000],
    )

    assert browser._scan_service is replacement
    assert browser._scan_ports == (7000,)
    assert browser._endpoint_snapshot == EndpointObservationSnapshot()
    assert browser.server_tree.topLevelItemCount() == 0
    assert refreshes == [True]
    assert terminated == [
        TransportEndpoint(
            host=original.host,
            port=5000,
            transport_mode=original.transport_mode,
        )
    ]


def test_kill_result_carries_the_exact_endpoint_selected_by_the_scan(
    qapp,
    monkeypatch,
) -> None:
    callbacks = []
    monkeypatch.setattr(
        "pyqt_reactive.widgets.shared.zmq_server_browser_widget.spawn_thread_with_context",
        lambda callback, *, name: callbacks.append((callback, name)),
    )
    scan_service = ZMQServerScanService(config=ZMQConfig(), transport_mode=None)
    browser = _Browser(
        ports_to_scan=[5000],
        title="Servers",
        color_scheme=ColorScheme(),
        scan_service=scan_service,
    )
    observed: list[TransportEndpoint] = []
    shutdown_endpoints: list[TransportEndpoint] = []
    browser.endpoint_terminated.connect(observed.append)

    class _ShutdownService:
        def shutdown_ports(self, *, ports, mode):
            del mode
            return EndpointShutdownBatchResult(
                (
                    EndpointShutdownOutcome(
                        port=ports[0],
                        result=EndpointShutdownResult(
                            succeeded=True,
                            endpoint_terminated=True,
                        ),
                    ),
                )
            )

    monkeypatch.setattr(
        EndpointShutdownService,
        "for_endpoint",
        classmethod(
            lambda cls, config, endpoint: shutdown_endpoints.append(endpoint) or _ShutdownService()
        ),
    )

    browser._spawn_server_kill_thread([5000], EndpointShutdownMode.GRACEFUL)
    callback, _name = callbacks.pop()
    callback()

    assert len(observed) == 1
    assert observed == [
        TransportEndpoint(
            host=scan_service.host,
            port=5000,
            transport_mode=scan_service.transport_mode,
        )
    ]
    assert shutdown_endpoints == observed


def test_startup_event_and_tree_share_the_endpoint_snapshot_authority(qapp) -> None:
    browser = _Browser(
        ports_to_scan=[5000],
        title="Servers",
        color_scheme=ColorScheme(),
        scan_service=_ScanService(),
    )
    published = []
    browser.endpoint_snapshot_changed.connect(published.append)
    status = EndpointStartupStatus(
        phase=EndpointStartupPhase.IMPORTING_RUNTIME,
        message="Importing runtime",
    )

    browser.observe_endpoint_startup(5000, status)

    assert browser._endpoint_snapshot.status_for_port(5000) is status
    assert published == [browser._endpoint_snapshot]
    row = browser.server_tree.topLevelItem(0)
    assert row.text(0) == "Port 5000 - Endpoint"
    assert row.text(1) == "🚀 Starting"
    assert row.text(2) == "Importing runtime"

    connected_status = EndpointStartupStatus(
        phase=EndpointStartupPhase.CONNECTED,
        message="Connected to endpoint",
    )
    browser.observe_endpoint_startup(5000, connected_status)
    row = browser.server_tree.topLevelItem(0)
    assert browser._endpoint_snapshot.status_for_port(5000) is connected_status
    assert row.text(1) == "✅ Connected"
    assert row.text(2) == "Connected to endpoint"

    browser.observe_endpoint_startup(
        5000,
        EndpointStartupStatus(
            phase=EndpointStartupPhase.FAILED,
            message="Import failed",
        ),
    )
    assert browser._endpoint_snapshot.observations == ()
    assert browser.server_tree.topLevelItemCount() == 0

    browser.deleteLater()
    QCoreApplication.sendPostedEvents(browser, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_scan_completion_is_suppressed_after_cleanup(qapp, monkeypatch) -> None:
    """A scan finishing after cleanup must not emit through a dead widget."""

    callbacks = []
    monkeypatch.setattr(
        "pyqt_reactive.widgets.shared.zmq_server_browser_widget.spawn_thread_with_context",
        lambda callback, *, name: callbacks.append((callback, name)),
    )
    browser = _Browser(
        ports_to_scan=[5000],
        title="Servers",
        color_scheme=ColorScheme(),
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
    assert not browser._scan_requests.has_outstanding()
    browser.deleteLater()
    QCoreApplication.sendPostedEvents(browser, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_scan_completion_is_suppressed_after_qt_destroys_browser(qapp, monkeypatch) -> None:
    """QObject destruction must close the lifecycle before a scan completes."""

    callbacks = []
    monkeypatch.setattr(
        "pyqt_reactive.widgets.shared.zmq_server_browser_widget.spawn_thread_with_context",
        lambda callback, *, name: callbacks.append((callback, name)),
    )
    browser = _Browser(
        ports_to_scan=[5000],
        title="Servers",
        color_scheme=ColorScheme(),
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
        color_scheme=ColorScheme(),
        scan_service=_ScanService(),
    )

    assert browser.refresh_timer.parent() is browser
    assert browser._cleanup_timer.parent() is browser

    browser.deleteLater()
    QCoreApplication.sendPostedEvents(browser, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_scan_invalidation_during_active_scan_runs_one_follow_up(qapp, monkeypatch) -> None:
    callbacks = []
    monkeypatch.setattr(
        "pyqt_reactive.widgets.shared.zmq_server_browser_widget.spawn_thread_with_context",
        lambda callback, *, name: callbacks.append((callback, name)),
    )
    browser = _Browser(
        ports_to_scan=[5000],
        title="Servers",
        color_scheme=ColorScheme(),
        scan_service=_ScanService(),
    )

    browser.refresh_servers()
    browser.refresh_servers()
    browser.refresh_servers()

    assert len(callbacks) == 1
    first_scan, _ = callbacks.pop()
    first_scan()
    assert len(callbacks) == 1
    follow_up_scan, _ = callbacks.pop()
    follow_up_scan()
    assert callbacks == []
    assert not browser._scan_requests.has_outstanding()

    browser.deleteLater()
    QCoreApplication.sendPostedEvents(browser, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_follow_up_scan_uses_the_committed_snapshot_authority(qapp, monkeypatch) -> None:
    callbacks = []
    monkeypatch.setattr(
        "pyqt_reactive.widgets.shared.zmq_server_browser_widget.spawn_thread_with_context",
        lambda callback, *, name: callbacks.append((callback, name)),
    )
    observed = EndpointObservationSnapshot.from_responses(
        (
            PongResponse(
                port=5000,
                control_port=6000,
                ready=True,
                server="ExecutionServer",
                server_role=ServerRole.EXECUTION,
                process_identity=ProcessIdentity.current(),
            ),
        )
    )
    scan_service = _SequencedScanService((observed, observed))
    browser = _Browser(
        ports_to_scan=[5000],
        title="Servers",
        color_scheme=ColorScheme(),
        scan_service=scan_service,
    )

    browser.refresh_servers()
    browser.refresh_servers()
    first_scan, _ = callbacks.pop()
    first_scan()

    assert browser._endpoint_snapshot is observed
    second_scan, _ = callbacks.pop()
    second_scan()
    assert scan_service.previous_snapshots == [
        EndpointObservationSnapshot(),
        observed,
    ]

    browser.deleteLater()
    QCoreApplication.sendPostedEvents(browser, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_lifecycle_commit_supersedes_an_older_in_flight_scan(qapp, monkeypatch) -> None:
    callbacks = []
    monkeypatch.setattr(
        "pyqt_reactive.widgets.shared.zmq_server_browser_widget.spawn_thread_with_context",
        lambda callback, *, name: callbacks.append((callback, name)),
    )
    scan_service = _SequencedScanService(
        (EndpointObservationSnapshot(), EndpointObservationSnapshot())
    )
    browser = _Browser(
        ports_to_scan=[5000],
        title="Servers",
        color_scheme=ColorScheme(),
        scan_service=scan_service,
    )

    browser.refresh_servers()
    startup_status = EndpointStartupStatus(
        phase=EndpointStartupPhase.PREPARING_CAPABILITIES,
        message="Preparing capabilities",
    )
    browser.observe_endpoint_startup(5000, startup_status)
    startup_snapshot = browser._endpoint_snapshot
    first_scan, _ = callbacks.pop()
    first_scan()

    assert browser._endpoint_snapshot.status_for_port(5000) is startup_status
    second_scan, _ = callbacks.pop()
    second_scan()
    assert scan_service.previous_snapshots == [
        EndpointObservationSnapshot(),
        startup_snapshot,
    ]

    browser.deleteLater()
    QCoreApplication.sendPostedEvents(browser, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_kill_completion_is_suppressed_after_cleanup(qapp, monkeypatch) -> None:
    """A kill finishing after cleanup must not emit through a dead widget."""

    callbacks = []
    monkeypatch.setattr(
        "pyqt_reactive.widgets.shared.zmq_server_browser_widget.spawn_thread_with_context",
        lambda callback, *, name: callbacks.append((callback, name)),
    )
    browser = _Browser(
        ports_to_scan=[5000],
        title="Servers",
        color_scheme=ColorScheme(),
        scan_service=_ScanService(),
    )
    completions = []
    terminated_ports = []
    browser._kill_complete.connect(lambda success, message: completions.append((success, message)))
    browser.endpoint_terminated.connect(terminated_ports.append)

    class _ShutdownService:
        def shutdown_ports(self, *, ports, mode):
            del mode
            return EndpointShutdownBatchResult(
                (
                    EndpointShutdownOutcome(
                        port=ports[0],
                        result=EndpointShutdownResult(
                            succeeded=True,
                            endpoint_terminated=True,
                        ),
                    ),
                )
            )

    monkeypatch.setattr(
        EndpointShutdownService,
        "for_endpoint",
        classmethod(lambda cls, config, endpoint: _ShutdownService()),
    )

    mode = EndpointShutdownMode.GRACEFUL
    browser._spawn_server_kill_thread([5000], mode)
    browser.cleanup()
    callback, name = callbacks.pop()
    callback()

    assert name == "graceful_endpoint_shutdown"
    assert completions == []
    assert terminated_ports == []
    browser.deleteLater()
    QCoreApplication.sendPostedEvents(browser, QEvent.Type.DeferredDelete)
    qapp.processEvents()
