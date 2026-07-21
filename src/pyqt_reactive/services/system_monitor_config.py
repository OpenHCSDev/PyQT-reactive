"""Nominal configuration owner for the system monitor widget."""

from __future__ import annotations

from dataclasses import dataclass, field

from pyqt_reactive.services.system_metrics_sampler import SystemMetricsSamplerConfig


@dataclass(frozen=True)
class PerformanceMonitorConfig:
    """Complete behavior configuration for :class:`SystemMonitorWidget`."""

    update_fps: float = 10.0
    """Metric sampling and plot-update frequency in frames per second."""

    history_duration_seconds: float = 60.0
    """Duration of historical data displayed by the plots."""

    max_data_points: int | None = None
    """Explicit retained sample count, or ``None`` to derive it from time and FPS."""

    sampler_config: SystemMetricsSamplerConfig = field(
        default_factory=SystemMetricsSamplerConfig
    )
    """Policy owned by the system metrics sampler."""

    show_grid: bool = True
    """Whether monitor plots display grid lines."""

    antialiasing: bool = True
    """Whether plot curves request antialiased rendering."""

    use_opengl: bool = True
    """Whether plots request pyqtgraph's OpenGL rendering path."""

    line_width: float = 2.0
    """Width of all monitor plot curves in pixels."""

    chart_colors: dict[str, str] = field(
        default_factory=lambda: {
            "cpu": "cyan",
            "ram": "lime",
            "gpu": "orange",
            "vram": "magenta",
        }
    )
    """Colors for the four declared monitor series."""

    def __post_init__(self) -> None:
        if self.update_fps <= 0:
            raise ValueError("update_fps must be positive")
        if self.history_duration_seconds <= 0:
            raise ValueError("history_duration_seconds must be positive")
        if self.max_data_points is not None and self.max_data_points <= 0:
            raise ValueError("max_data_points must be positive when provided")
        if self.line_width <= 0:
            raise ValueError("line_width must be positive")

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
