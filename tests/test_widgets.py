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
    from pyqt_reactive.forms.widget_strategies import create_pyqt6_widget

    class Mode(str, Enum):
        A = "a"
        B = "b"

    widget = create_pyqt6_widget(
        "mode",
        Mode | str,
        Mode.A,
        "mode_widget",
    )

    assert isinstance(widget, QComboBox)
    assert widget.count() == 2
    assert widget.itemData(0) is Mode.A


def test_action_tabbed_window_body_switches_active_actions(qapp):
    """Action tab bodies expose only the current tab's actions."""
    from PyQt6.QtWidgets import QLabel, QPushButton
    from pyqt_reactive.widgets.shared.action_tabbed_window_body import (
        ActionTabSpec,
        ActionTabbedWindowBody,
    )

    body = ActionTabbedWindowBody()
    first_actions = QPushButton("first")
    second_actions = QPushButton("second")

    body.add_tab(ActionTabSpec("First", QLabel("first content"), first_actions))
    body.add_tab(ActionTabSpec("Second", QLabel("second content"), second_actions))
    body.show()

    body.set_current_index(0)
    qapp.processEvents()
    assert first_actions.isVisible()
    assert not second_actions.isVisible()

    body.set_current_index(1)
    qapp.processEvents()
    assert not first_actions.isVisible()
    assert second_actions.isVisible()


def test_form_window_action_header_exposes_stable_actions(qapp):
    """Form headers keep title and actions behind stable IDs."""
    from PyQt6.QtWidgets import QPushButton
    from pyqt_reactive.widgets.shared.form_window_action_header import (
        FormWindowActionHeader,
        HeaderAction,
        HeaderActionGroup,
    )

    save_button = QPushButton("Save")
    cancel_button = QPushButton("Cancel")

    header = FormWindowActionHeader(
        title_text="Configure Example",
        action_groups=[
            HeaderActionGroup(
                "save_group",
                [
                    HeaderAction("cancel", cancel_button),
                    HeaderAction("save", save_button),
                ],
            )
        ],
        stay_priority=["save_group"],
        right_aligned_group_ids=["save_group"],
    )

    assert header.header_label.text() == "Configure Example"
    assert header.action("save") is save_button
    assert header.action("cancel") is cancel_button
