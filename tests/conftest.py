"""pytest configuration and fixtures for pyqt-reactor tests."""

import pytest
from PyQt6.QtWidgets import QApplication

from pyqt_reactive.theming import ColorScheme, ThemeManager


@pytest.fixture(scope="session")
def qapp():
    """Create one fully themed QApplication for the test process."""
    app = QApplication.instance() or QApplication([])
    color_scheme = ColorScheme()
    ThemeManager(color_scheme).apply_color_scheme(color_scheme)
    yield app
    # Don't quit - may cause issues with other tests


class FrozenClock:
    """Flash clock that moves only when a test advances it.

    Flash phases change only with this clock, so the event loop can paint at
    any speed without moving a playback past the phase a test checks.
    """

    def __init__(self) -> None:
        self.now = 1000.0

    def perf_counter(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def flash_clock(monkeypatch):
    """Drive the flash coordinator's clock explicitly."""
    from types import SimpleNamespace

    from pyqt_reactive.animation import flash_mixin

    clock = FrozenClock()
    monkeypatch.setattr(flash_mixin, "time", SimpleNamespace(perf_counter=clock.perf_counter))
    return clock
