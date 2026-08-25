"""Contracts for noninteractive background subprocess creation."""

from __future__ import annotations

import subprocess
from pathlib import Path
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


def test_windows_background_python_uses_windowed_interpreter(
    tmp_path: Path,
) -> None:
    python_executable = tmp_path / "python.exe"
    windowed_executable = tmp_path / "pythonw.exe"
    python_executable.touch()
    windowed_executable.touch()

    policy = BackgroundProcessLaunchPolicy(
        platform=BackgroundProcessPlatform.WINDOWS,
    )

    assert policy.python_executable(str(python_executable)) == str(
        windowed_executable
    )


def test_background_python_keeps_original_when_windowed_interpreter_is_absent(
    tmp_path: Path,
) -> None:
    python_executable = tmp_path / "python.exe"
    python_executable.touch()

    policy = BackgroundProcessLaunchPolicy(
        platform=BackgroundProcessPlatform.WINDOWS,
    )

    assert policy.python_executable(str(python_executable)) == str(
        python_executable
    )


def test_non_windows_background_python_keeps_requested_interpreter(
    tmp_path: Path,
) -> None:
    python_executable = tmp_path / "python"
    python_executable.touch()
    (tmp_path / "pythonw.exe").touch()

    policy = BackgroundProcessLaunchPolicy(
        platform=BackgroundProcessPlatform.OTHER,
    )

    assert policy.python_executable(str(python_executable)) == str(
        python_executable
    )


class _ConsumerLaunchPolicy:
    @classmethod
    def current(cls, *, detached=False):
        assert detached is False
        return SimpleNamespace(
            popen_arguments=lambda: {"creationflags": 73},
            python_executable=lambda _executable: "windowed-python",
        )


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
    system_metrics_sampler.PersistentNvidiaSmiPoller(
        cadence=system_metrics_sampler.PollingCadence(1.0),
        temperature_sampling=(
            system_metrics_sampler.GpuTemperatureSampling.ENABLED
        ),
    ).start()

    assert check_output_calls[0]["creationflags"] == 73
    assert popen_calls[0]["creationflags"] == 73


def test_log_highlighter_uses_background_process_policy(monkeypatch) -> None:
    captured: dict[str, object] = {}
    process = SimpleNamespace(
        poll=lambda: None,
        terminate=lambda: None,
        wait=lambda timeout=None: None,
    )
    monkeypatch.setattr(
        log_highlight_client,
        "BackgroundProcessLaunchPolicy",
        _ConsumerLaunchPolicy,
    )
    monkeypatch.setattr(
        log_highlight_client.subprocess,
        "Popen",
        lambda command, **kwargs: (
            captured.update(command=command, **kwargs) or process
        ),
    )
    client = log_highlight_client.LogHighlightClient()
    try:
        assert client._ensure_process() is process
        assert captured["command"][0] == "windowed-python"
        assert captured["creationflags"] == 73
    finally:
        client.shutdown()
