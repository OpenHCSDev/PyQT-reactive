"""Nominal configuration owner for the system monitor widget."""

from __future__ import annotations

from dataclasses import dataclass, field

from python_introspect import validate_annotated_dataclass
from pyqt_reactive.qt_types import QtColorText
from pyqt_reactive.services.system_metrics_sampler import SystemMetricsSamplerConfig
from zmqruntime.config import PositiveFloat, PositiveInteger


@dataclass(frozen=True, slots=True)
class PerformanceMonitorColors:
    """Colors for the declared system-monitor series."""

    cpu: QtColorText = "cyan"
    """Qt color name or literal used for the CPU utilization series."""

    ram: QtColorText = "lime"
    """Qt color name or literal used for the system-memory series."""

    gpu: QtColorText = "orange"
    """Qt color name or literal used for the GPU utilization series."""

    vram: QtColorText = "magenta"
    """Qt color name or literal used for the GPU-memory series."""

    def __post_init__(self) -> None:
        validate_annotated_dataclass(self)


@dataclass(frozen=True)
class PerformanceMonitorConfig:
    """Complete behavior configuration for :class:`SystemMonitorWidget`."""

    update_fps: PositiveFloat = 10.0
    """Metric sampling and plot-update frequency in frames per second."""

    history_duration_seconds: PositiveFloat = 60.0
    """Duration of historical data displayed by the plots."""

    max_data_points: PositiveInteger | None = None
    """Explicit retained sample count, or ``None`` to derive it from time and FPS."""

    sampler_config: SystemMetricsSamplerConfig = field(default_factory=SystemMetricsSamplerConfig)
    """Policy owned by the system metrics sampler."""

    show_grid: bool = True
    """Whether monitor plots display grid lines."""

    antialiasing: bool = True
    """Whether plot curves request antialiased rendering."""

    use_opengl: bool = True
    """Whether plots request pyqtgraph's OpenGL rendering path."""

    line_width: PositiveFloat = 2.0
    """Width of all monitor plot curves in pixels."""

    colors: PerformanceMonitorColors = field(default_factory=PerformanceMonitorColors)
    """Colors for the four declared monitor series."""

    def __post_init__(self) -> None:
        validate_annotated_dataclass(self)

    @property
    def update_interval_seconds(self) -> float:
        """Sampling interval derived from :attr:`update_fps`."""

        return 1.0 / self.update_fps

    @property
    def calculated_max_data_points(self) -> int:
        """Retained sample count derived from the declared history policy."""

        if self.max_data_points is not None:
            return self.max_data_points
        return max(
            1,
            int(self.history_duration_seconds / self.update_interval_seconds),
        )
