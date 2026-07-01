"""Cached system metrics sampling for monitor widgets."""

from __future__ import annotations

import platform
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Any, Callable

import psutil

try:
    import GPUtil
    GPU_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on optional runtime package
    GPUtil = None
    GPU_AVAILABLE = False


def is_wsl() -> bool:
    """Check if running in Windows Subsystem for Linux."""
    return "microsoft" in platform.uname().release.lower()


def get_cpu_freq_mhz() -> int:
    """Get CPU frequency in MHz, with WSL compatibility."""
    if is_wsl():
        try:
            output = subprocess.check_output(
                [
                    "powershell.exe",
                    "-Command",
                    "Get-CimInstance -ClassName Win32_Processor | Select-Object -ExpandProperty CurrentClockSpeed",
                ],
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
            return int(output.strip())
        except Exception:
            return 0
    try:
        freq = psutil.cpu_freq()
        return int(freq.current) if freq else 0
    except Exception:
        return 0


class BackgroundMetricPoller:
    """Run one blocking metric probe on a background cadence."""

    def __init__(
        self,
        *,
        name: str,
        refresh_seconds: float,
        probe: Callable[[], Any],
        default: Any,
    ) -> None:
        self.refresh_seconds = max(0.1, float(refresh_seconds))
        self._probe = probe
        self._value = default
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._name = name
        self._thread: threading.Thread | None = None
        self._closed = False

    def latest(self) -> Any:
        self.start()
        with self._lock:
            return self._value

    def start(self) -> None:
        if self._closed or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._closed = True
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                value = self._probe()
            except Exception:
                value = self.latest()
            with self._lock:
                self._value = value
            self._stop_event.wait(self.refresh_seconds)


@dataclass(frozen=True, slots=True)
class SystemMetricsSamplerConfig:
    """Typed policy for expensive system metric providers."""

    enable_gpu_monitoring: bool = True
    gpu_temperature_monitoring: bool = True
    cpu_frequency_monitoring: bool = True
    gpu_refresh_seconds: float = 1.0
    cpu_frequency_refresh_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.gpu_refresh_seconds <= 0:
            raise ValueError("gpu_refresh_seconds must be positive")
        if self.cpu_frequency_refresh_seconds <= 0:
            raise ValueError("cpu_frequency_refresh_seconds must be positive")


@dataclass(frozen=True, slots=True)
class GpuMetrics:
    """Typed GPU metrics snapshot."""

    gpu_percent: float = 0.0
    vram_percent: float = 0.0
    gpu_name: str = "GPU Pending"
    gpu_temp: float = 0.0
    vram_used_mb: float = 0.0
    vram_total_mb: float = 0.0

    @classmethod
    def unavailable(cls, name: str) -> "GpuMetrics":
        return cls(gpu_name=name)


@dataclass(frozen=True, slots=True)
class SystemMetrics:
    """Typed system metrics snapshot."""

    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    ram_used_gb: float = 0.0
    ram_total_gb: float = 0.0
    ram_available_gb: float = 0.0
    cpu_cores: int = 0
    cpu_freq_mhz: int = 0
    gpu_percent: float = 0.0
    vram_percent: float = 0.0
    gpu_name: str = "GPU Pending"
    gpu_temp: float = 0.0
    vram_used_mb: float = 0.0
    vram_total_mb: float = 0.0

    @classmethod
    def from_components(
        cls,
        *,
        cpu_percent: float,
        ram,
        cpu_cores: int,
        cpu_freq_mhz: int,
        gpu: GpuMetrics,
    ) -> "SystemMetrics":
        return cls(
            cpu_percent=cpu_percent,
            ram_percent=ram.percent,
            ram_used_gb=ram.used / (1024**3),
            ram_total_gb=ram.total / (1024**3),
            ram_available_gb=ram.available / (1024**3),
            cpu_cores=cpu_cores,
            cpu_freq_mhz=cpu_freq_mhz,
            gpu_percent=gpu.gpu_percent,
            vram_percent=gpu.vram_percent,
            gpu_name=gpu.gpu_name,
            gpu_temp=gpu.gpu_temp,
            vram_used_mb=gpu.vram_used_mb,
            vram_total_mb=gpu.vram_total_mb,
        )

    @classmethod
    def error(cls) -> "SystemMetrics":
        return cls(gpu_name="Error")

    def as_dict(self) -> dict[str, Any]:
        """Convert to the legacy flat dict consumed by existing UI code."""
        return {
            "cpu_percent": self.cpu_percent,
            "ram_percent": self.ram_percent,
            "ram_used_gb": self.ram_used_gb,
            "ram_total_gb": self.ram_total_gb,
            "ram_available_gb": self.ram_available_gb,
            "cpu_cores": self.cpu_cores,
            "cpu_freq_mhz": self.cpu_freq_mhz,
            "gpu_percent": self.gpu_percent,
            "vram_percent": self.vram_percent,
            "gpu_name": self.gpu_name,
            "gpu_temp": self.gpu_temp,
            "vram_used_mb": self.vram_used_mb,
            "vram_total_mb": self.vram_total_mb,
        }


def _parse_number(value: str) -> float:
    cleaned = value.strip().replace("%", "")
    if cleaned in {"", "N/A", "[N/A]"}:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


class PersistentNvidiaSmiPoller:
    """Maintain latest NVIDIA GPU metrics from one long-lived nvidia-smi process."""

    def __init__(
        self,
        *,
        refresh_seconds: float = 1.0,
        gpu_temperature_monitoring: bool = True,
    ) -> None:
        self.refresh_seconds = max(0.1, float(refresh_seconds))
        self.gpu_temperature_monitoring = gpu_temperature_monitoring
        self._lock = threading.Lock()
        self._latest_metrics = GpuMetrics.unavailable("GPU Pending")
        self._process: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self._start_attempted = False
        self._closed = False

    def latest_metrics(self) -> GpuMetrics:
        """Return latest cached GPU metrics, starting the poller if needed."""
        self.start()
        with self._lock:
            return self._latest_metrics

    def start(self) -> None:
        if self._closed or self._process is not None or self._start_attempted:
            return
        self._start_attempted = True

        executable = shutil.which("nvidia-smi")
        if executable is None:
            with self._lock:
                self._latest_metrics = GpuMetrics.unavailable("NVIDIA SMI Not Available")
            return

        loop_ms = max(100, int(self.refresh_seconds * 1000))
        command = [
            executable,
            "--id=0",
            "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total,name",
            "--format=csv,noheader,nounits",
            f"--loop-ms={loop_ms}",
        ]
        try:
            self._process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except Exception:
            self._process = None
            with self._lock:
                self._latest_metrics = GpuMetrics.unavailable("NVIDIA SMI Error")
            return

        self._thread = threading.Thread(
            target=self._read_loop,
            name="NvidiaSmiPoller",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._closed = True
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            process.terminate()
            process.wait(timeout=1.0)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _read_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return

        try:
            for line in process.stdout:
                parsed = self._parse_gpu_line(line)
                if parsed is None:
                    continue
                with self._lock:
                    self._latest_metrics = parsed
        finally:
            with self._lock:
                if self._latest_metrics.gpu_name == "GPU Pending":
                    self._latest_metrics = GpuMetrics.unavailable("NVIDIA SMI Error")

    def _parse_gpu_line(self, line: str) -> GpuMetrics | None:
        parts = [part.strip() for part in line.strip().split(",", 4)]
        if len(parts) != 5:
            return None

        gpu_percent = _parse_number(parts[0])
        gpu_temp = _parse_number(parts[1]) if self.gpu_temperature_monitoring else 0
        vram_used_mb = _parse_number(parts[2])
        vram_total_mb = _parse_number(parts[3])
        gpu_name = parts[4] or "NVIDIA GPU"
        vram_percent = (
            (vram_used_mb / vram_total_mb) * 100.0
            if vram_total_mb > 0
            else 0.0
        )
        return GpuMetrics(
            gpu_percent=gpu_percent,
            vram_percent=vram_percent,
            gpu_name=gpu_name,
            gpu_temp=gpu_temp,
            vram_used_mb=vram_used_mb,
            vram_total_mb=vram_total_mb,
        )


class SystemMetricsSampler:
    """Collect cheap per-tick metrics while caching slow system probes."""

    def __init__(
        self,
        config: SystemMetricsSamplerConfig | None = None,
    ) -> None:
        self.config = config or SystemMetricsSamplerConfig()
        self.enable_gpu_monitoring = self.config.enable_gpu_monitoring
        self.gpu_temperature_monitoring = self.config.gpu_temperature_monitoring
        self.cpu_frequency_monitoring = self.config.cpu_frequency_monitoring
        self.gpu_refresh_seconds = max(0.1, float(self.config.gpu_refresh_seconds))
        self.cpu_frequency_refresh_seconds = max(
            0.1,
            float(self.config.cpu_frequency_refresh_seconds),
        )

        self._cpu_cores = psutil.cpu_count() or 0
        self._cpu_frequency_poller = (
            BackgroundMetricPoller(
                name="CpuFrequencyPoller",
                refresh_seconds=self.cpu_frequency_refresh_seconds,
                probe=get_cpu_freq_mhz,
                default=0,
            )
            if self.cpu_frequency_monitoring
            else None
        )
        self._gpu_metrics = self._initial_gpu_metrics()
        self._gpu_poller = (
            PersistentNvidiaSmiPoller(
                refresh_seconds=self.gpu_refresh_seconds,
                gpu_temperature_monitoring=self.gpu_temperature_monitoring,
            )
            if self.enable_gpu_monitoring
            else None
        )

    def collect_metrics(self) -> SystemMetrics:
        """Collect a monitor sample, refreshing expensive probes only on schedule."""
        cpu_percent = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory()

        return SystemMetrics.from_components(
            cpu_percent=cpu_percent,
            ram=ram,
            cpu_cores=self._cpu_cores,
            cpu_freq_mhz=self._cached_cpu_frequency(),
            gpu=self._cached_gpu_metrics(),
        )

    def _cached_cpu_frequency(self) -> int:
        if self._cpu_frequency_poller is None:
            return 0
        return int(self._cpu_frequency_poller.latest() or 0)

    def _cached_gpu_metrics(self) -> GpuMetrics:
        if not self.enable_gpu_monitoring:
            return GpuMetrics.unavailable("GPU Monitoring Disabled")
        if self._gpu_poller is not None:
            self._gpu_metrics = self._gpu_poller.latest_metrics()
            return self._gpu_metrics
        self._gpu_metrics = self._read_gpu_metrics()
        return self._gpu_metrics

    def _read_gpu_metrics(self) -> GpuMetrics:
        if not GPU_AVAILABLE or GPUtil is None:
            return GpuMetrics.unavailable("GPUtil Not Available")

        try:
            gpus = GPUtil.getGPUs()
            if not gpus:
                return GpuMetrics.unavailable("No GPU Found")

            gpu = gpus[0]
            return GpuMetrics(
                gpu_percent=gpu.load * 100,
                vram_percent=gpu.memoryUtil * 100,
                gpu_name=gpu.name,
                gpu_temp=gpu.temperature if self.gpu_temperature_monitoring else 0,
                vram_used_mb=gpu.memoryUsed,
                vram_total_mb=gpu.memoryTotal,
            )
        except Exception:
            return GpuMetrics.unavailable("GPU Error")

    def _initial_gpu_metrics(self) -> GpuMetrics:
        if not self.enable_gpu_monitoring:
            return GpuMetrics.unavailable("GPU Monitoring Disabled")
        return GpuMetrics.unavailable("GPU Pending")

    def close(self) -> None:
        """Stop any background metric providers owned by this sampler."""
        if self._cpu_frequency_poller is not None:
            self._cpu_frequency_poller.stop()
        if self._gpu_poller is not None:
            self._gpu_poller.stop()
