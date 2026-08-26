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
