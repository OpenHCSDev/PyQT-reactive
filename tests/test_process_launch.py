"""Contracts for noninteractive background subprocess creation."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

from pyqt_reactive.process_launch import (
    BackgroundProcessLaunchPolicy,
    BackgroundProcessLaunchSpec,
    BackgroundProcessPlatform,
)
from pyqt_reactive.services import system_metrics_sampler
from pyqt_reactive.utils import log_highlight_client


def test_windows_background_process_suppresses_console(monkeypatch) -> None:
    no_window = 0x08000000
    new_process_group = 0x00000200
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", no_window, raising=False)
    monkeypatch.setattr(
        subprocess,
        "CREATE_NEW_PROCESS_GROUP",
        new_process_group,
        raising=False,
    )

    attached = BackgroundProcessLaunchPolicy(
        platform=BackgroundProcessPlatform.WINDOWS,
    )
    detached = BackgroundProcessLaunchPolicy(
        platform=BackgroundProcessPlatform.WINDOWS,
        detached=True,
    )

    assert attached.resolve() == BackgroundProcessLaunchSpec(
        creationflags=no_window
    )
    assert detached.popen_arguments() == {
        "creationflags": no_window | new_process_group
    }


def test_non_windows_background_process_detaches_without_windows_flags() -> None:
    attached = BackgroundProcessLaunchPolicy(
        platform=BackgroundProcessPlatform.OTHER,
    )
    detached = BackgroundProcessLaunchPolicy(
        platform=BackgroundProcessPlatform.OTHER,
        detached=True,
    )

    assert attached.popen_arguments() == {}
    assert detached.resolve() == BackgroundProcessLaunchSpec(
        start_new_session=True
    )


class _ConsumerLaunchPolicy:
    @classmethod
    def current(cls, *, detached=False):
        assert detached is False
        return SimpleNamespace(popen_arguments=lambda: {"creationflags": 73})


def test_system_metric_helpers_use_background_process_policy(monkeypatch) -> None:
    check_output_calls: list[dict[str, object]] = []
    popen_calls: list[dict[str, object]] = []
    process = SimpleNamespace(stdout=())

    monkeypatch.setattr(system_metrics_sampler, "is_wsl", lambda: True)
    monkeypatch.setattr(
        system_metrics_sampler,
        "BackgroundProcessLaunchPolicy",
        _ConsumerLaunchPolicy,
    )
    monkeypatch.setattr(
        system_metrics_sampler.subprocess,
        "check_output",
        lambda _command, **kwargs: check_output_calls.append(kwargs) or b"2400",
    )
    monkeypatch.setattr(
        system_metrics_sampler.shutil,
        "which",
        lambda _name: "nvidia-smi",
    )
    monkeypatch.setattr(
        system_metrics_sampler.subprocess,
        "Popen",
        lambda _command, **kwargs: popen_calls.append(kwargs) or process,
    )
    monkeypatch.setattr(
        system_metrics_sampler.threading,
        "Thread",
        lambda **_kwargs: SimpleNamespace(start=lambda: None),
    )

    assert system_metrics_sampler.get_cpu_freq_mhz() == 2400
    system_metrics_sampler.PersistentNvidiaSmiPoller().start()

    assert check_output_calls[0]["creationflags"] == 73
    assert popen_calls[0]["creationflags"] == 73


def test_log_highlighter_uses_background_process_policy(monkeypatch) -> None:
    captured: dict[str, object] = {}
    process = SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(
        log_highlight_client,
        "BackgroundProcessLaunchPolicy",
        _ConsumerLaunchPolicy,
    )
    monkeypatch.setattr(
        log_highlight_client.subprocess,
        "Popen",
        lambda _command, **kwargs: captured.update(kwargs) or process,
    )
    log_highlight_client.LogHighlightClient._proc = None
    try:
        assert log_highlight_client.LogHighlightClient._ensure_process() is process
        assert captured["creationflags"] == 73
    finally:
        log_highlight_client.LogHighlightClient._proc = None
