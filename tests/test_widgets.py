"""Tests for extended widgets."""

from enum import Enum

import pytest


def test_no_scroll_spinbox(qapp):
    """Test NoScrollSpinBox creation."""
    from pyqt_reactive.widgets import NoScrollSpinBox
    
    widget = NoScrollSpinBox()
    assert widget is not None


def test_none_aware_checkbox(qapp):
    """Test NoneAwareCheckBox creation."""
    from pyqt_reactive.widgets import NoneAwareCheckBox
    
    widget = NoneAwareCheckBox()
    assert widget is not None


def test_enum_union_uses_enum_widget(qapp):
    """Enum unions retain the closed-domain enum widget."""
    from PyQt6.QtWidgets import QComboBox
    from pyqt_reactive.forms.widget_strategies import MagicGuiWidgetFactory

    class Mode(str, Enum):
        A = "a"
        B = "b"

    widget = MagicGuiWidgetFactory().create_widget(
        "mode",
        Mode | str,
        Mode.A,
        "mode_widget",
    )

    assert isinstance(widget, QComboBox)
    assert widget.count() == 2
    assert widget.itemData(0) is Mode.A
