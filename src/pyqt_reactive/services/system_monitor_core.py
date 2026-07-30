"""
System Monitor Core - Framework-agnostic metrics collection.

This module provides pure system metrics collection without any visualization dependencies.
Can be used by any UI framework (PyQt, Textual, etc.) for system monitoring.
"""

from collections import deque
from dataclasses import dataclass
import platform
import time

import psutil

from pyqt_reactive.services.system_metrics_sampler import (
    GPUtil,
    GPU_AVAILABLE,
    SystemMetrics,
    SystemMetricsSampler,
    SystemMetricsSamplerConfig,
)


@dataclass(frozen=True, slots=True)
class SystemMetricsHistory:
    """Immutable history snapshot from one monitor."""

    cpu: tuple[float, ...]
    ram: tuple[float, ...]
    gpu: tuple[float, ...]
    vram: tuple[float, ...]
    timestamps: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class SystemInformation:
    """Static system information projected by the monitor."""

    operating_system: str
    operating_system_version: str
    cpu_cores: int | None
    ram_total_gb: float
    gpu_name: str | None = None
    vram_total_mb: float | None = None


class SystemMonitorCore:
    """
    Framework-agnostic system monitoring core.
    
    Collects CPU, RAM, GPU, and VRAM metrics without any visualization dependencies.
    Maintains historical data in deques for efficient time-series tracking.
    """
    
    def __init__(
        self,
        history_length: int = 60,
        *,
        sampler_config: SystemMetricsSamplerConfig | None = None,
    ):
        """
        Initialize the system monitor core.
        
        Args:
            history_length: Number of historical data points to keep
        """
        self.history_length = history_length

        # Initialize data storage
        self.cpu_history = deque(maxlen=history_length)
        self.ram_history = deque(maxlen=history_length)
        self.gpu_history = deque(maxlen=history_length)
        self.vram_history = deque(maxlen=history_length)
        self.time_stamps = deque(maxlen=history_length)

        # Cache current metrics to avoid duplicate system calls
        self._current_metrics = SystemMetrics()
        self.sampler_config = sampler_config or SystemMetricsSamplerConfig()
        self._sampler = SystemMetricsSampler(self.sampler_config)
        
        # Initialize with zeros
        for _ in range(history_length):
            self.cpu_history.append(0)
            self.ram_history.append(0)
            self.gpu_history.append(0)
            self.vram_history.append(0)
            self.time_stamps.append(0)
    
    def update_metrics(self) -> None:
        """
        Update system metrics and cache current values.
        
        Collects CPU, RAM, GPU, and VRAM usage and appends to history.
        Updates the typed internal cache for efficient access.
        """
        metrics = self._sampler.collect_metrics()
        self.cpu_history.append(metrics.cpu_percent)
        self.ram_history.append(metrics.ram_percent)
        self.gpu_history.append(metrics.gpu_percent)
        self.vram_history.append(metrics.vram_percent)
        self._current_metrics = metrics

        # Update timestamps
        self.time_stamps.append(time.time())
    
    def get_metrics(self) -> SystemMetrics:
        """Return the latest typed metrics snapshot without sampling again."""

        return self._current_metrics
    
    def get_system_info(self) -> SystemInformation:
        """Return one typed static system-information snapshot."""

        gpu_name = None
        vram_total_mb = None
        if GPU_AVAILABLE:
            try:
                gpus = GPUtil.getGPUs()
                if gpus:
                    gpu = gpus[0]
                    gpu_name = gpu.name
                    vram_total_mb = gpu.memoryTotal
            except Exception:
                pass

        return SystemInformation(
            operating_system=platform.system(),
            operating_system_version=platform.version(),
            cpu_cores=psutil.cpu_count(),
            ram_total_gb=psutil.virtual_memory().total / (1024**3),
            gpu_name=gpu_name,
            vram_total_mb=vram_total_mb,
        )
    
    def reset_history(self) -> None:
        """Reset all historical data to zeros."""
        self.cpu_history.clear()
        self.ram_history.clear()
        self.gpu_history.clear()
        self.vram_history.clear()
        self.time_stamps.clear()
        
        # Re-initialize with zeros
        for _ in range(self.history_length):
            self.cpu_history.append(0)
            self.ram_history.append(0)
            self.gpu_history.append(0)
            self.vram_history.append(0)
            self.time_stamps.append(0)
        
        self._current_metrics = SystemMetrics()

    def close(self) -> None:
        """Stop background metric providers owned by this monitor core."""
        self._sampler.close()
