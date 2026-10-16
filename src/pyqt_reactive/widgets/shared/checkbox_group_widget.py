"""Enum-list layout over the shared Qt field-input owner."""

from enum import Enum

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout

from objectstate import Unset
from pyqt_reactive.protocols.widget_adapters import CheckboxGroupAdapter
from pyqt_reactive.widgets import InheritedCheckBox


class CheckboxGroupWidget(CheckboxGroupAdapter):
    """Lay out enum choices; the adapter owns values and input subscriptions."""

    selection_changed = pyqtSignal()

    def __init__(self, param_name: str, enum_type: type[Enum], current_value=Unset(), parent=None):
        super().__init__(parent)
        self.setTitle(param_name.replace('_', ' ').title())
        self._enum_type = enum_type
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        for member in enum_type:
            checkbox = InheritedCheckBox()
            checkbox.setText(member.name.replace('_', ' ').title())
            layout.addWidget(checkbox)
            self._checkboxes[member] = checkbox
        self.set_value(current_value)
        self.connect_change_signal(lambda _value: self.selection_changed.emit())
