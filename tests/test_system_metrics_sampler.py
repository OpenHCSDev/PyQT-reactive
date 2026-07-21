from __future__ import annotations

import threading
from dataclasses import dataclass, replace

import pytest

from pyqt_reactive.services import system_metrics_sampler as sampler_module
from pyqt_reactive.services.system_metrics_sampler import (
    BackgroundMetricPoller,
    GpuMetrics,
    PersistentNvidiaSmiPoller,
    SystemMetrics,
    SystemMetricsSampler,
    SystemMetricsSamplerConfig,
)


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    percent: float
    used: int
    total: int
    available: int


class FakeCpuFrequencyPoller:
    created: list["FakeCpuFrequencyPoller"] = []

    def __init__(self, *, name, refresh_seconds, probe, default) -> None:
        self.name = name
        self.refresh_seconds = refresh_seconds
        self.probe = probe
        self.default = default
        self.stopped = False
        self.__class__.created.append(self)

    def latest(self) -> int:
        return 2400

    def stop(self) -> None:
        self.stopped = True


class FakeGpuMetricsPoller:
    created: list["FakeGpuMetricsPoller"] = []

    def __init__(self, *, refresh_seconds, gpu_temperature_monitoring) -> None:
        self.refresh_seconds = refresh_seconds
        self.gpu_temperature_monitoring = gpu_temperature_monitoring
        self.stopped = False
        self.__class__.created.append(self)

    def latest_metrics(self) -> GpuMetrics:
        return GpuMetrics(
            gpu_percent=12.5,
            vram_percent=25.0,
            gpu_name="Test GPU",
            gpu_temp=61.0,
            vram_used_mb=2048.0,
            vram_total_mb=8192.0,
        )

    def stop(self) -> None:
        self.stopped = True


def test_sampler_returns_typed_metrics_from_cached_background_providers(monkeypatch) -> None:
    FakeCpuFrequencyPoller.created.clear()
    FakeGpuMetricsPoller.created.clear()
    monkeypatch.setattr(sampler_module.psutil, "cpu_count", lambda: 16)
    monkeypatch.setattr(sampler_module.psutil, "cpu_percent", lambda interval=None: 7.5)
    monkeypatch.setattr(
        sampler_module.psutil,
        "virtual_memory",
        lambda: MemorySnapshot(
            percent=40.0,
            used=4 * 1024**3,
            total=16 * 1024**3,
            available=12 * 1024**3,
        ),
    )
    monkeypatch.setattr(sampler_module, "BackgroundMetricPoller", FakeCpuFrequencyPoller)
    monkeypatch.setattr(sampler_module, "PersistentNvidiaSmiPoller", FakeGpuMetricsPoller)

    config = SystemMetricsSamplerConfig(
        enable_gpu_monitoring=True,
        gpu_temperature_monitoring=True,
        cpu_frequency_monitoring=True,
        gpu_refresh_seconds=0.25,
        cpu_frequency_refresh_seconds=2.0,
    )
    sampler = SystemMetricsSampler(config)

    metrics = sampler.collect_metrics()

    assert isinstance(metrics, SystemMetrics)
    assert metrics.cpu_percent == 7.5
    assert metrics.cpu_cores == 16
    assert metrics.cpu_freq_mhz == 2400
    assert metrics.ram_total_gb == 16
    assert metrics.gpu_name == "Test GPU"
    assert metrics.vram_percent == 25.0
    assert metrics.as_dict()["gpu_percent"] == 12.5
    assert FakeCpuFrequencyPoller.created[0].refresh_seconds == 2.0
    assert FakeGpuMetricsPoller.created[0].refresh_seconds == 0.25

    sampler.close()

    assert FakeCpuFrequencyPoller.created[0].stopped is True
    assert FakeGpuMetricsPoller.created[0].stopped is True


def test_nvidia_smi_poller_parses_typed_metrics() -> None:
    poller = PersistentNvidiaSmiPoller(
        refresh_seconds=0.5,
        gpu_temperature_monitoring=True,
    )

    metrics = poller._parse_gpu_line("12, 63, 2048, 8192, NVIDIA RTX")

    assert metrics == GpuMetrics(
        gpu_percent=12.0,
        vram_percent=25.0,
        gpu_name="NVIDIA RTX",
        gpu_temp=63.0,
        vram_used_mb=2048.0,
        vram_total_mb=8192.0,
    )


def test_nvidia_smi_poller_respects_temperature_policy() -> None:
    poller = PersistentNvidiaSmiPoller(
        refresh_seconds=0.5,
        gpu_temperature_monitoring=False,
    )

    metrics = poller._parse_gpu_line("12, 63, 2048, 8192, NVIDIA RTX")

    assert metrics.gpu_temp == 0


def test_enable_gpu_monitoring_leaf_disables_gpu_provider(monkeypatch) -> None:
    monkeypatch.setattr(sampler_module, "PersistentNvidiaSmiPoller", FakeGpuMetricsPoller)
    config = replace(SystemMetricsSamplerConfig(), enable_gpu_monitoring=False)

    sampler = SystemMetricsSampler(config)

    assert sampler._gpu_poller is None
    assert sampler._cached_gpu_metrics().gpu_name == "GPU Monitoring Disabled"
    sampler.close()


def test_gpu_temperature_monitoring_leaf_reaches_gpu_provider(monkeypatch) -> None:
    FakeGpuMetricsPoller.created.clear()
    monkeypatch.setattr(sampler_module, "PersistentNvidiaSmiPoller", FakeGpuMetricsPoller)
    config = replace(SystemMetricsSamplerConfig(), gpu_temperature_monitoring=False)

    sampler = SystemMetricsSampler(config)

    assert FakeGpuMetricsPoller.created[-1].gpu_temperature_monitoring is False
    sampler.close()


def test_cpu_frequency_monitoring_leaf_disables_frequency_provider(monkeypatch) -> None:
    monkeypatch.setattr(sampler_module, "BackgroundMetricPoller", FakeCpuFrequencyPoller)
    config = replace(SystemMetricsSamplerConfig(), cpu_frequency_monitoring=False)

    sampler = SystemMetricsSampler(config)

    assert sampler._cpu_frequency_poller is None
    assert sampler._cached_cpu_frequency() == 0
    sampler.close()


def test_gpu_refresh_seconds_leaf_reaches_gpu_provider(monkeypatch) -> None:
    FakeGpuMetricsPoller.created.clear()
    monkeypatch.setattr(sampler_module, "PersistentNvidiaSmiPoller", FakeGpuMetricsPoller)
    config = replace(SystemMetricsSamplerConfig(), gpu_refresh_seconds=0.25)

    sampler = SystemMetricsSampler(config)

    assert FakeGpuMetricsPoller.created[-1].refresh_seconds == 0.25
    sampler.close()


def test_cpu_frequency_refresh_seconds_leaf_reaches_frequency_provider(
    monkeypatch,
) -> None:
    FakeCpuFrequencyPoller.created.clear()
    monkeypatch.setattr(sampler_module, "BackgroundMetricPoller", FakeCpuFrequencyPoller)
    config = replace(SystemMetricsSamplerConfig(), cpu_frequency_refresh_seconds=2.0)

    sampler = SystemMetricsSampler(config)

    assert FakeCpuFrequencyPoller.created[-1].refresh_seconds == 2.0
    sampler.close()


def test_background_metric_poller_is_lazy_and_does_not_restart_after_stop() -> None:
    probe_called = threading.Event()

    def probe() -> int:
        probe_called.set()
        return 3200

    poller = BackgroundMetricPoller(
        name="TestMetricPoller",
        refresh_seconds=60.0,
        probe=probe,
        default=0,
    )

    assert probe_called.is_set() is False
    assert poller.latest() in {0, 3200}
    assert probe_called.wait(timeout=1.0) is True
    assert poller.latest() == 3200

    poller.stop()
    probe_called.clear()

    assert poller.latest() == 3200
    assert probe_called.is_set() is False


@pytest.mark.parametrize(
    "config_kwargs",
    (
        {"gpu_refresh_seconds": 0},
        {"cpu_frequency_refresh_seconds": 0},
    ),
)
def test_sampler_config_rejects_nonpositive_refresh_intervals(config_kwargs) -> None:
    with pytest.raises(ValueError):
        SystemMetricsSamplerConfig(**config_kwargs)
