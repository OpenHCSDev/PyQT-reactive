"""Lifecycle regressions for asynchronous log loading."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import qInstallMessageHandler

from pyqt_reactive.protocols import register_log_discovery_provider
from pyqt_reactive.utils.log_highlighter import build_log_line_html
from pyqt_reactive.widgets.log_viewer import (
    LogFileInfo,
    LogFileLoader,
    LogViewerWindow,
)


def test_log_line_html_uses_authoritative_highlight_segments() -> None:
    rendered = build_log_line_html(
        "2026-07-29 20:00:00,000 - worker - ERROR - value < 2"
    )

    assert "ERROR" in rendered
    assert "font-weight: 700" in rendered
    assert "&lt;" in rendered
    assert ">2</span>" in rendered


class _LogDiscoveryProvider:
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
        return [LogFileInfo(path=self.main_log_path, log_type="main")]


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
            if "Destroyed while process" in message
            or "Destroyed while thread" in message
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
