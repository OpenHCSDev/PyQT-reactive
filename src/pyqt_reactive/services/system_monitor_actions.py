"""Lightweight action declarations for the system monitor."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import TYPE_CHECKING, Self

from pyqt_reactive.services.executable_action import LabeledExecutableActionMixin

if TYPE_CHECKING:
    from pyqt_reactive.widgets.system_monitor import SystemMonitorWidget


class SystemMonitorAction(LabeledExecutableActionMixin, StrEnum):
    """Declared system-monitor actions with member-owned execution leaves."""

    tooltip: str

    def __new__(
        cls,
        value: str,
        label: str,
        tooltip: str,
        executor: Callable[[SystemMonitorWidget], None],
    ) -> Self:
        member = cls._new_member(value, label, executor)
        member.tooltip = tooltip
        return member

    GLOBAL_CONFIG = (
        "global_config",
        "Global Config",
        "Open global configuration editor",
        lambda widget: widget.show_global_config.emit(),
    )
    LOG_VIEWER = (
        "log_viewer",
        "Log Viewer",
        "Open log viewer window",
        lambda widget: widget.show_log_viewer.emit(),
    )
    CUSTOM_FUNCTIONS = (
        "custom_functions",
        "Custom Functions",
        "Manage custom functions",
        lambda widget: widget.show_custom_functions.emit(),
    )
    TEST_PLATE = (
        "test_plate",
        "Test Plate",
        "Generate synthetic test plate",
        lambda widget: widget.show_test_plate_generator.emit(),
    )

    @property
    def button_config(self) -> tuple[str, str, str]:
        """Project this action into the generic button-panel contract."""

        return self.label, self.value, self.tooltip
