"""Placeholder refresh respects the nominal widget capability boundary."""

from __future__ import annotations


def test_single_placeholder_refresh_skips_structural_groupbox(qapp):
    from PyQt6.QtWidgets import QGroupBox

    from pyqt_reactive.services.parameter_ops_service import ParameterOpsService

    class Manager:
        field_id = ""

        def __init__(self) -> None:
            self.widgets = {"optional_config": QGroupBox()}

        @property
        def parameters(self):
            raise AssertionError(
                "Structural widgets must be rejected before value resolution."
            )

    ParameterOpsService().refresh_single_placeholder(
        Manager(),
        "optional_config",
    )
