"""Lightweight action declarations for the function-list editor."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import TYPE_CHECKING, Self

from pyqt_reactive.services.executable_action import LabeledExecutableActionMixin

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QPushButton

    from pyqt_reactive.widgets.function_list_editor import FunctionListEditorWidget


class FunctionListEditorAction(LabeledExecutableActionMixin, StrEnum):
    """Function-editor actions with member-owned presentation and execution."""

    maximum_width: int

    def __new__(
        cls,
        value: str,
        label: str,
        maximum_width: int,
        executor: Callable[[FunctionListEditorWidget], None],
    ) -> Self:
        member = cls._new_member(value, label, executor)
        member.maximum_width = maximum_width
        return member

    ADD = (
        "add",
        "Add",
        60,
        lambda widget: widget.add_function(),
    )
    CODE = (
        "code",
        "Code",
        60,
        lambda widget: widget.edit_function_code(),
    )
    COMPONENT = (
        "component",
        "Component",
        120,
        lambda widget: widget.show_component_selection_dialog(),
    )
    PREVIOUS_PATTERN = (
        "previous_pattern",
        "<",
        30,
        lambda widget: widget._navigate_pattern_key(-1),
    )
    NEXT_PATTERN = (
        "next_pattern",
        ">",
        30,
        lambda widget: widget._navigate_pattern_key(1),
    )

    def create_button(self, widget: FunctionListEditorWidget) -> QPushButton:
        """Create one button directly from this action declaration."""

        from PyQt6.QtWidgets import QPushButton

        from pyqt_reactive.forms.layout_constants import CURRENT_LAYOUT

        button = QPushButton(self.label)
        button.setObjectName(self.object_name)
        button.setMaximumWidth(self.maximum_width)
        button.setFixedHeight(CURRENT_LAYOUT.button_height)
        button.setStyleSheet(widget._get_button_style())
        button.clicked.connect(lambda _checked=False: self.invoke(widget))
        return button

    @property
    def object_name(self) -> str:
        """Return the declaration-derived Qt identity for this action."""

        return f"function_list_editor_action_{self.value}"
