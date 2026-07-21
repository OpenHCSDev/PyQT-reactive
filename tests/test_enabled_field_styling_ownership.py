from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtWidgets import QVBoxLayout, QWidget

from pyqt_reactive.forms.parameter_form_tree_index import ParameterFormTreeIndex
from pyqt_reactive.forms.widget_strategies import NoneAwareLineEdit
from pyqt_reactive.services.enabled_field_styling_service import (
    EnabledFieldStylingService,
)


def test_direct_widget_discovery_excludes_nested_form_tree(qapp) -> None:
    """A manager styles only values outside its declared child containers."""
    manager = QWidget()
    layout = QVBoxLayout(manager)
    direct_widget = NoneAwareLineEdit(manager)
    layout.addWidget(direct_widget)

    nested_container = QWidget(manager)
    nested_layout = QVBoxLayout(nested_container)
    nested_widget = NoneAwareLineEdit(nested_container)
    nested_layout.addWidget(nested_widget)
    layout.addWidget(nested_container)

    manager.nested_managers = {
        "child": SimpleNamespace(field_id="child"),
    }
    manager.field_id = ""
    manager.widgets = {"child": nested_container}
    manager.form_tree = ParameterFormTreeIndex(manager)

    direct_widgets = EnabledFieldStylingService()._get_direct_widgets(manager)

    assert direct_widget in direct_widgets
    assert nested_widget not in direct_widgets
