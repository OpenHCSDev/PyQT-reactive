"""Tests for extended widgets."""

import pytest


def test_no_scroll_spinbox(qapp):
    """Test NoScrollSpinBox creation."""
    from pyqt_reactor.widgets import NoScrollSpinBox
    
    widget = NoScrollSpinBox()
    assert widget is not None


def test_none_aware_checkbox(qapp):
    """Test NoneAwareCheckBox creation."""
    from pyqt_reactor.widgets import NoneAwareCheckBox
    
    widget = NoneAwareCheckBox()
    assert widget is not None
