"""Lifecycle regressions for asynchronous log loading."""

from __future__ import annotations

import time
from pathlib import Path

from PyQt6.QtCore import Qt, qInstallMessageHandler
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QStyleOptionViewItem
from zmqruntime.messages import ProcessIdentity

from pyqt_reactive.core.log_utils import LogType
from pyqt_reactive.protocols import (
    LogDiscoveryProviderABC,
    ServerScanProviderABC,
    register_log_discovery_provider,
    register_server_scan_provider,
)
from pyqt_reactive.services.process_tracker import ProcessLiveness
from pyqt_reactive.utils.log_highlighter import build_log_line_html
from pyqt_reactive.widgets.log_viewer import (
    LogFileDetector,
    LogFileInfo,
    LogFileLoader,
    LogItemDelegate,
    LogListModel,
    LogTailer,
    LogViewerWindow,
)


def test_log_delegate_uses_pyqt6_item_data_role(qtbot) -> None:
    """Search and sizing must use PyQt6's scoped item-data enum."""

    model = LogListModel()
    model.append_lines(["alpha", "matching line"])
    delegate = LogItemDelegate()
    delegate.set_search_state("matching", case_sensitive=False)

    try:
        delegate._precompute_search_matches(model)
        hint = delegate.sizeHint(QStyleOptionViewItem(), model.index(1, 0))

        assert delegate._search_match_rows == {1}
        assert model.data(model.index(1, 0), Qt.ItemDataRole.DisplayRole) == "matching line"
        assert hint.isValid()
    finally:
        delegate.cleanup()


def test_log_delegate_cleanup_closes_and_joins_highlighting_tasks(
    qtbot,
    monkeypatch,
) -> None:
    """Delegate cleanup closes its client before Qt can destroy worker signals."""

    started = []

    def wait_until_closed(client, _text):
        started.append(True)
        while not client._closed:
            time.sleep(0.001)
        return []

    monkeypatch.setattr(
        "pyqt_reactive.utils.log_highlight_client.LogHighlightClient.parse_line",
        wait_until_closed,
    )
    delegate = LogItemDelegate()
    delegate._get_or_request_segments("background line", QFont("Consolas", 10))
    qtbot.waitUntil(lambda: started == [True])

    delegate.cleanup()

    assert delegate._highlighting_cleaned_up
    assert delegate._thread_pool.activeThreadCount() == 0
    assert delegate._pending_highlights == set()


def test_log_line_html_uses_authoritative_highlight_segments() -> None:
    rendered = build_log_line_html("2026-07-29 20:00:00,000 - worker - ERROR - value < 2")

    assert "ERROR" in rendered
    assert "font-weight: 700" in rendered
    assert "&lt;" in rendered
    assert ">2</span>" in rendered


class _LogDiscoveryProvider(LogDiscoveryProviderABC):
    def __init__(self, main_log_path: Path) -> None:
        self.main_log_path = main_log_path

    def get_current_log_path(self) -> Path:
        return self.main_log_path

    def discover_logs(
        self,
        base_log_path=None,
        include_main_log: bool = True,
        log_directory=None,
    ) -> list[LogFileInfo]:
        if not include_main_log:
            return []
        return [LogFileInfo(path=self.main_log_path, log_type=LogType.MAIN)]


class _SequencedServerScanProvider(ServerScanProviderABC):
    def __init__(self, scans: list[list[LogFileInfo]]) -> None:
        self._scans = iter(scans)

    def scan_for_server_logs(self) -> list[LogFileInfo]:
        return next(self._scans)


def test_log_file_detector_classifies_new_path_through_injected_provider(
    qtbot,
    tmp_path,
) -> None:
    """A watched file is classified by the window's host-owned provider."""

    main_log_path = tmp_path / "main.log"
    provider = _LogDiscoveryProvider(main_log_path)
    detector = LogFileDetector(log_discovery_provider=provider)
    discovered = []
    detector.new_log_detected.connect(discovered.append)

    main_log_path.write_text("started\n", encoding="utf-8")
    detector._on_directory_changed(str(tmp_path))

    assert discovered == [LogFileInfo(path=main_log_path, log_type=LogType.MAIN)]


def test_visible_log_viewer_discovers_server_started_after_initial_scan(
    qtbot,
    tmp_path,
    monkeypatch,
) -> None:
    """A server launched after construction appears on the next visible refresh."""

    main_log_path = tmp_path / "main.log"
    server_log_path = tmp_path / "server.log"
    main_log_path.write_text("main\n", encoding="utf-8")
    server_log_path.write_text("server\n", encoding="utf-8")
    register_log_discovery_provider(_LogDiscoveryProvider(main_log_path))
    register_server_scan_provider(
        _SequencedServerScanProvider(
            [
                [],
                [LogFileInfo(path=server_log_path, log_type=LogType.ZMQ_SERVER)],
            ]
        )
    )
    callbacks = []
    monkeypatch.setattr(
        "pyqt_reactive.widgets.log_viewer.spawn_thread_with_context",
        lambda callback, *, name: callbacks.append((callback, name)),
    )
    monkeypatch.setattr(LogViewerWindow, "_scan_subprocess_logs_async", lambda self: None)
    monkeypatch.setattr(LogViewerWindow, "start_monitoring", lambda self: None)
    monkeypatch.setattr(LogViewerWindow, "start_process_tracking", lambda self: None)

    viewer = LogViewerWindow(file_manager=None, service_adapter=None)
    try:
        assert [name for _callback, name in callbacks] == ["scan_server_logs"]
        viewer.show()
        qtbot.waitExposed(viewer)
        assert viewer.server_scan_timer.isActive()

        initial_scan, _name = callbacks.pop(0)
        initial_scan()
        refresh_scan, refresh_name = callbacks.pop(0)
        assert refresh_name == "scan_server_logs"
        refresh_scan()

        discovered_paths = {
            viewer.log_selector.itemData(index).path for index in range(viewer.log_selector.count())
        }
        assert discovered_paths == {main_log_path, server_log_path}

        viewer.hide()
        assert not viewer.server_scan_timer.isActive()
    finally:
        viewer.cleanup()


def _disable_external_discovery(monkeypatch) -> None:
    monkeypatch.setattr(
        LogViewerWindow,
        "_scan_subprocess_logs_async",
        lambda self: None,
    )
    monkeypatch.setattr(LogViewerWindow, "_scan_servers_async", lambda self: None)
    monkeypatch.setattr(LogViewerWindow, "start_monitoring", lambda self: None)
    monkeypatch.setattr(LogViewerWindow, "start_process_tracking", lambda self: None)


def test_log_file_loader_runs_as_interruptible_qthread(qtbot, tmp_path) -> None:
    """The loader must use its QThread lifecycle rather than an owned process."""

    log_path = tmp_path / "main.log"
    log_path.write_text("first\nsecond\nthird\n", encoding="utf-8")
    loader = LogFileLoader(log_path, tail_lines=2, chunk_lines=1)
    started = []
    chunks = []
    completed = []
    loader.started.connect(lambda: started.append(True))
    loader.chunk_loaded.connect(lambda owner, lines: chunks.append((owner, lines)))
    loader.load_finished.connect(completed.append)

    loader.start()
    qtbot.waitUntil(lambda: completed == [loader])
    loader.wait()

    assert started == [True]
    assert [chunk[1][0]["text"] for chunk in chunks] == ["second", "third"]
    assert all(owner is loader for owner, _chunk in chunks)


def test_log_tailer_honors_stop_requested_before_run(qapp, tmp_path) -> None:
    """A stop requested during QThread startup cannot be overwritten by run()."""

    tailer = LogTailer(tmp_path / "main.log")
    tailer.request_stop()
    tailer.start()

    assert tailer.wait(1_000)
    assert not tailer.isRunning()


def test_rapid_log_switching_retires_workers_without_qt_lifecycle_failure(
    qtbot,
    tmp_path,
    monkeypatch,
) -> None:
    """Superseded loads cannot destroy a running worker or update the new view."""

    main_log_path = tmp_path / "main.log"
    second_log_path = tmp_path / "second.log"
    main_log_path.write_text(
        "".join(f"main line {index}\n" for index in range(1_000)),
        encoding="utf-8",
    )
    second_log_path.write_text("second\n", encoding="utf-8")
    register_log_discovery_provider(_LogDiscoveryProvider(main_log_path))
    _disable_external_discovery(monkeypatch)

    qt_messages = []
    previous_message_handler = qInstallMessageHandler(
        lambda _kind, _context, message: qt_messages.append(message)
    )
    viewer = LogViewerWindow(file_manager=None, service_adapter=None)
    try:
        for _index in range(10):
            viewer.switch_to_log(second_log_path)
            viewer.switch_to_log(main_log_path)

        qtbot.waitUntil(
            lambda: (
                viewer.file_loader is not None
                and not viewer.file_loader.isRunning()
                and viewer.log_model.rowCount() == 1_001
            ),
            timeout=5_000,
        )

        assert viewer.current_log_path == main_log_path
        assert viewer.log_model.data(viewer.log_model.index(1_000, 0)) == "main line 999"
        assert not [
            message
            for message in qt_messages
            if "Destroyed while process" in message or "Destroyed while thread" in message
        ]
    finally:
        viewer.cleanup()
        qInstallMessageHandler(previous_message_handler)

    assert viewer.file_loader is None
    assert viewer._file_loaders == set()


def test_cleanup_joins_an_active_file_loader(qapp, tmp_path, monkeypatch) -> None:
    """Closing during initial loading leaves no live worker owned by the viewer."""

    main_log_path = tmp_path / "main.log"
    main_log_path.write_text(
        "".join(f"line {index}\n" for index in range(10_000)),
        encoding="utf-8",
    )
    register_log_discovery_provider(_LogDiscoveryProvider(main_log_path))
    _disable_external_discovery(monkeypatch)
    viewer = LogViewerWindow(file_manager=None, service_adapter=None)

    viewer.cleanup()

    assert viewer.file_loader is None
    assert viewer._file_loaders == set()


def test_dropdown_refresh_preserves_exact_programmatic_log_selection(
    qtbot,
    tmp_path,
    monkeypatch,
) -> None:
    """An asynchronous discovery refresh cannot replace a server-log selection."""

    main_log_path = tmp_path / "main.log"
    server_log_path = tmp_path / "server.log"
    later_log_path = tmp_path / "later.log"
    for path, text in (
        (main_log_path, "main\n"),
        (server_log_path, "server\n"),
        (later_log_path, "later\n"),
    ):
        path.write_text(text, encoding="utf-8")
    register_log_discovery_provider(_LogDiscoveryProvider(main_log_path))
    _disable_external_discovery(monkeypatch)
    viewer = LogViewerWindow(file_manager=None, service_adapter=None)
    try:
        viewer.switch_to_log(server_log_path)
        viewer._on_subprocess_scan_complete(
            [
                LogFileInfo(
                    path=later_log_path,
                    log_type=LogType.WORKER,
                    worker_id="1",
                )
            ]
        )

        selected = viewer.log_selector.itemData(viewer.log_selector.currentIndex())
        assert viewer.current_log_path == server_log_path
        assert selected.path == server_log_path
    finally:
        viewer.cleanup()


def test_live_filter_requires_confirmed_pid_reuse_safe_liveness(
    qapp,
    tmp_path,
    monkeypatch,
) -> None:
    """Unknown logs and reused PIDs are not presented as live processes."""

    main_log_path = tmp_path / "main.log"
    main_log_path.write_text("main\n", encoding="utf-8")
    register_log_discovery_provider(_LogDiscoveryProvider(main_log_path))
    _disable_external_discovery(monkeypatch)
    viewer = LogViewerWindow(file_manager=None, service_adapter=None)
    try:
        current = ProcessIdentity.current()
        live = LogFileInfo(
            path=tmp_path / "live.log",
            log_type=LogType.ZMQ_SERVER,
            process_identity=current,
        )
        reused = LogFileInfo(
            path=tmp_path / "reused.log",
            log_type=LogType.ZMQ_SERVER,
            process_identity=ProcessIdentity(
                pid=current.pid,
                create_time=current.create_time - 10,
            ),
        )
        pid_only = LogFileInfo(
            path=tmp_path / f"worker_{current.pid}.log",
            log_type=LogType.WORKER,
            worker_id=str(current.pid),
        )
        unknown = LogFileInfo(
            path=tmp_path / "unknown.log",
            log_type=LogType.UNKNOWN,
        )
        viewer._update_tracked_processes([live, reused, pid_only, unknown])

        assert viewer._is_log_from_alive_process(live)
        assert not viewer._is_log_from_alive_process(reused)
        assert viewer.process_tracker.log_liveness(pid_only) is ProcessLiveness.UNKNOWN
        assert not viewer._is_log_from_alive_process(pid_only)
        assert not viewer._is_log_from_alive_process(unknown)
    finally:
        viewer.cleanup()
