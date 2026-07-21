from __future__ import annotations

from dataclasses import fields, replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import pyqt_reactive.widgets.system_monitor as system_monitor_module
from pyqt_reactive.services.system_metrics_sampler import SystemMetricsSamplerConfig
from pyqt_reactive.services.system_monitor_config import PerformanceMonitorConfig
from pyqt_reactive.widgets.system_monitor import SystemMonitorWidget


class FakeCoreMonitor:
    created: list[FakeCoreMonitor] = []

    def __init__(self, history_length, *, sampler_config) -> None:
        self.history_length = history_length
        self.sampler_config = sampler_config
        self.__class__.created.append(self)


class FakePersistentMonitor:
    created: list[FakePersistentMonitor] = []

    def __init__(self, update_interval, history_length, *, sampler_config) -> None:
        self.update_interval = update_interval
        self.history_length = history_length
        self.sampler_config = sampler_config
        self.stopped = False
        self.started = False
        self.connected = False
        self.__class__.created.append(self)

    def stop_monitoring(self) -> None:
        self.stopped = True

    def start_monitoring(self) -> None:
        self.started = True

    def connect_signals(self, metrics_callback, error_callback) -> None:
        self.metrics_callback = metrics_callback
        self.error_callback = error_callback
        self.connected = True


class FakeCurve:
    def __init__(self) -> None:
        self.pens: list[object] = []
        self.data_calls: list[dict[str, object]] = []

    def setPen(self, pen) -> None:  # noqa: N802 - mirrors the Qt API
        self.pens.append(pen)

    def setData(self, *args, **kwargs) -> None:  # noqa: N802 - mirrors the Qt API
        del args
        self.data_calls.append(kwargs)

    def setClipToView(self, enabled: bool) -> None:  # noqa: N802 - mirrors the Qt API
        self.clip_to_view = enabled

    def setDownsampling(self, **kwargs) -> None:  # noqa: N802 - mirrors the Qt API
        self.downsampling = kwargs


class FakePlot:
    def __init__(self) -> None:
        self.opengl_calls: list[bool] = []
        self.grid_calls: list[tuple[bool, bool, float]] = []
        self.ranges: list[tuple[float, float, int]] = []

    def useOpenGL(self, enabled: bool) -> None:  # noqa: N802 - mirrors the Qt API
        self.opengl_calls.append(enabled)

    def showGrid(self, *, x: bool, y: bool, alpha: float) -> None:  # noqa: N802
        self.grid_calls.append((x, y, alpha))

    def setXRange(  # noqa: N802 - mirrors the Qt API
        self,
        left: float,
        right: float,
        *,
        padding: int,
    ) -> None:
        self.ranges.append((left, right, padding))


class FakePyqtgraph:
    def __init__(self) -> None:
        self.options: list[tuple[str, object]] = []

    def setConfigOption(self, name: str, value) -> None:  # noqa: N802
        self.options.append((name, value))

    @staticmethod
    def mkPen(color: str, *, width: float):  # noqa: N802 - mirrors pyqtgraph
        return color, width


def fake_widget(config: PerformanceMonitorConfig, *, with_plots: bool = False):
    methods = {
        name: method
        for name, method in vars(SystemMonitorWidget).items()
        if callable(method) and not name.startswith("__")
    }
    widget_type = type("FakeSystemMonitorWidget", (SimpleNamespace,), methods)
    old_persistent = FakePersistentMonitor(
        config.update_interval_seconds,
        config.calculated_max_data_points,
        sampler_config=config.sampler_config,
    )
    attributes = {
        "monitor_config": config,
        "monitor": object(),
        "persistent_monitor": old_persistent,
        "_history_length": 1,
        "_history_x": object(),
        "_history_cpu": object(),
        "_history_ram": object(),
        "_history_gpu": object(),
        "_history_vram": object(),
        "_history_update_interval": config.update_interval_seconds,
        "_last_plot_history": config.history_duration_seconds,
        "_gpu_series_visible": True,
        "_vram_series_visible": True,
        "on_metrics_updated": Mock(),
        "on_metrics_error": Mock(),
    }
    if with_plots:
        attributes.update(
            cpu_gpu_plot=FakePlot(),
            ram_vram_plot=FakePlot(),
            cpu_curve=FakeCurve(),
            ram_curve=FakeCurve(),
            gpu_curve=FakeCurve(),
            vram_curve=FakeCurve(),
            _plot_opengl_enabled=False,
        )
    return widget_type(**attributes), old_persistent


@pytest.mark.parametrize(
    ("field_name", "value", "expected_interval", "expected_history"),
    (
        ("update_fps", 5.0, 0.2, 300),
        ("history_duration_seconds", 30.0, 0.1, 300),
        ("max_data_points", 47, 0.1, 47),
    ),
)
def test_each_sampling_history_leaf_rebuilds_owned_monitors(
    monkeypatch,
    field_name,
    value,
    expected_interval,
    expected_history,
) -> None:
    FakeCoreMonitor.created.clear()
    FakePersistentMonitor.created.clear()
    monkeypatch.setattr(system_monitor_module, "SystemMonitorCore", FakeCoreMonitor)
    monkeypatch.setattr(
        system_monitor_module,
        "PersistentSystemMonitor",
        FakePersistentMonitor,
    )
    original = PerformanceMonitorConfig()
    widget, old_persistent = fake_widget(original)
    updated = replace(original, **{field_name: value})

    SystemMonitorWidget.update_config(widget, updated)

    assert old_persistent.stopped is True
    assert widget.monitor_config is updated
    assert widget.monitor is FakeCoreMonitor.created[-1]
    assert widget.monitor.history_length == expected_history
    assert widget.persistent_monitor.update_interval == expected_interval
    assert widget.persistent_monitor.history_length == expected_history
    assert widget.persistent_monitor.started is True
    assert widget.persistent_monitor.connected is True


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("enable_gpu_monitoring", False),
        ("gpu_temperature_monitoring", False),
        ("cpu_frequency_monitoring", False),
        ("gpu_refresh_seconds", 0.25),
        ("cpu_frequency_refresh_seconds", 2.0),
    ),
)
def test_each_sampler_leaf_rebuilds_monitor_with_exact_nominal_policy(
    monkeypatch,
    field_name,
    value,
) -> None:
    FakeCoreMonitor.created.clear()
    FakePersistentMonitor.created.clear()
    monkeypatch.setattr(system_monitor_module, "SystemMonitorCore", FakeCoreMonitor)
    monkeypatch.setattr(
        system_monitor_module,
        "PersistentSystemMonitor",
        FakePersistentMonitor,
    )
    original = PerformanceMonitorConfig()
    widget, old_persistent = fake_widget(original)
    sampler_config = replace(original.sampler_config, **{field_name: value})
    updated = replace(original, sampler_config=sampler_config)

    SystemMonitorWidget.update_config(widget, updated)

    assert old_persistent.stopped is True
    assert widget.monitor.sampler_config is sampler_config
    assert widget.persistent_monitor.sampler_config is sampler_config
    assert getattr(widget.persistent_monitor.sampler_config, field_name) == value


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("show_grid", False),
        ("antialiasing", False),
        ("use_opengl", False),
        ("line_width", 7.0),
        (
            "chart_colors",
            {
                "cpu": "red",
                "ram": "blue",
                "gpu": "yellow",
                "vram": "white",
            },
        ),
    ),
)
def test_each_plot_leaf_reconfigures_existing_plots(
    monkeypatch,
    field_name,
    value,
) -> None:
    fake_pg = FakePyqtgraph()
    monkeypatch.setattr(system_monitor_module, "pg", fake_pg)
    original = PerformanceMonitorConfig()
    widget, old_persistent = fake_widget(original, with_plots=True)
    updated = replace(original, **{field_name: value})

    SystemMonitorWidget.update_config(widget, updated)

    assert old_persistent.stopped is False
    assert widget.monitor_config is updated
    assert widget.cpu_gpu_plot.grid_calls[-1][:2] == (
        updated.show_grid,
        updated.show_grid,
    )
    assert widget.ram_vram_plot.grid_calls[-1][:2] == (
        updated.show_grid,
        updated.show_grid,
    )
    assert widget.cpu_gpu_plot.opengl_calls[-1] is updated.use_opengl
    assert widget.ram_vram_plot.opengl_calls[-1] is updated.use_opengl
    assert ("antialias", updated.antialiasing) in fake_pg.options
    assert widget.cpu_curve.data_calls[-1]["antialias"] is updated.antialiasing
    assert widget.cpu_curve.pens[-1] == (
        updated.chart_colors["cpu"],
        updated.line_width,
    )
    assert widget.ram_curve.pens[-1] == (
        updated.chart_colors["ram"],
        updated.line_width,
    )


def test_history_duration_leaf_updates_plot_window_with_fixed_sample_capacity(
    monkeypatch,
) -> None:
    fake_pg = FakePyqtgraph()
    monkeypatch.setattr(system_monitor_module, "pg", fake_pg)
    original = PerformanceMonitorConfig(max_data_points=47)
    widget, old_persistent = fake_widget(original, with_plots=True)
    updated = replace(original, history_duration_seconds=30.0)

    SystemMonitorWidget.update_config(widget, updated)

    assert old_persistent.stopped is False
    assert widget.cpu_gpu_plot.ranges[-1] == (-30.0, 0.0, 0)
    assert widget.ram_vram_plot.ranges[-1] == (-30.0, 0.0, 0)


def test_retained_config_leaves_have_one_field_behavior_cases() -> None:
    direct_fields = {field.name for field in fields(PerformanceMonitorConfig)}
    sampler_fields = {field.name for field in fields(SystemMetricsSamplerConfig)}

    assert direct_fields == {
        "update_fps",
        "history_duration_seconds",
        "max_data_points",
        "sampler_config",
        "show_grid",
        "antialiasing",
        "use_opengl",
        "line_width",
        "chart_colors",
    }
    assert sampler_fields == {
        "enable_gpu_monitoring",
        "gpu_temperature_monitoring",
        "cpu_frequency_monitoring",
        "gpu_refresh_seconds",
        "cpu_frequency_refresh_seconds",
    }
