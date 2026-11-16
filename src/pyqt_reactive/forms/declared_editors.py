"""Qt editor family for declared comms forms.

Each editor is an empty crossing class: shared editing behavior from Formbridge,
native Qt control from PySide6. Adding a kind is adding a class (Prop 4.2).
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterable
from enum import Enum
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLineEdit,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from formbridge.forms.declared_fields import Multiline
from formbridge.forms.value_editing import (
    ChoicesEditing,
    ControlConstruction,
    EnumEditing,
    LineEditing,
    MultilineEditing,
    OptionalEditing,
    SelectEditing,
    ValueEditing,
)
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from python_introspect import AnnotationChoices


class QtValueEditor(ValueEditing):
    """Shared Qt editing mixin — signal, feedback and paint.

    Shiboken's sbktype() caps at 3 bases, so the signal lives here.
    Concrete editors: ControlConstruction + QtValueEditor + native control,
    metaclass=PyQtWidgetMeta. The editing parents come before the Qt widget so
    DeclaredViews takes each member's ``shows`` keyword before Shiboken's
    ``__init_subclass__`` would swallow it.
    """

    feedback_changed = Signal(str)

    def display_feedback(self, text: str) -> None:
        self.setToolTip(text)
        self.feedback_changed.emit(text)

    def clear_feedback(self) -> None:
        self.setToolTip("")
        self.feedback_changed.emit("")

    @abstractmethod
    def paint(self) -> None:
        """Repaint the control from the field's current value."""


class QtBoolEditor(ControlConstruction, QtValueEditor, QCheckBox, metaclass=PyQtWidgetMeta, shows=(bool,)):

    def control_arguments(self) -> dict[str, object]:
        return {}

    def bind_control(self) -> None:
        self.setChecked(bool(self.field.value))
        self.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool) -> None:
        self.send(checked)

    def paint(self) -> None:
        self.blockSignals(True)
        self.setChecked(bool(self.field.value))
        self.blockSignals(False)


class QtLineEditor(LineEditing, ControlConstruction, QtValueEditor, QLineEdit, metaclass=PyQtWidgetMeta):

    def control_arguments(self) -> dict[str, object]:
        return {}

    def bind_control(self) -> None:
        self.setText(self.value_text(self.field.value))
        self.editingFinished.connect(self.finish)

    def read_text(self) -> str:
        return self.text()

    def finish(self) -> None:
        """Commit the typed text: on Enter, on leaving the control, or when the form
        finishes before it reads its values."""
        text = self.read_text()
        if text == self.value_text(self.field.value):
            return
        try:
            value = self.read(text)
        except (TypeError, ValueError) as error:
            self.refuse(error)
            self.paint()
        else:
            self.send(value)

    def paint(self) -> None:
        self.blockSignals(True)
        self.setText(self.value_text(self.field.value))
        self.blockSignals(False)


class QtIntEditor(QtLineEditor, shows=(int,)):
    def read(self, text: str) -> int:
        return int(text)


class QtFloatEditor(QtLineEditor, shows=(float,)):
    def read(self, text: str) -> float:
        return float(text)


class QtStrEditor(QtLineEditor, shows=(str,)):
    pass


class QtMultilineEditor(MultilineEditing, ControlConstruction, QtValueEditor, QTextEdit, metaclass=PyQtWidgetMeta, shows=(Multiline,)):

    def control_arguments(self) -> dict[str, object]:
        return {}

    def bind_control(self) -> None:
        self.setAcceptRichText(False)
        self.setPlainText(str(self.field.value or ""))
        self.textChanged.connect(self._on_changed)

    def _on_changed(self) -> None:
        self.send(self.toPlainText())

    def paint(self) -> None:
        value = str(self.field.value or "")
        if self.toPlainText() != value:
            self.blockSignals(True)
            self.setPlainText(value)
            self.blockSignals(False)


class QtSelectEditor(SelectEditing, ControlConstruction, QtValueEditor, QComboBox, metaclass=PyQtWidgetMeta):

    def control_arguments(self) -> dict[str, object]:
        return {}

    def bind_control(self) -> None:
        for label, value in self.options():
            self.addItem(label, value)
        self._paint_selection()
        self.activated.connect(self._on_activated)

    def displayed_options(self) -> Iterable[tuple[str, object]]:
        return ((self.itemText(i), self.itemData(i)) for i in range(self.count()))

    def _on_activated(self, index: int) -> None:
        if index >= 0:
            self.send(self.itemData(index))

    def _paint_selection(self) -> None:
        value = self.field.value
        for i in range(self.count()):
            if self.itemData(i) == value:
                self.blockSignals(True)
                self.setCurrentIndex(i)
                self.blockSignals(False)
                return
        self.setCurrentIndex(-1)

    def paint(self) -> None:
        self._paint_selection()


class QtChoicesEditor(ChoicesEditing, QtSelectEditor, shows=(AnnotationChoices,)):

    def paint(self) -> None:
        self.blockSignals(True)
        self.clear()
        for label, value in self.options():
            self.addItem(label, value)
        self.blockSignals(False)
        self._paint_selection()


class QtEnumEditor(EnumEditing, QtSelectEditor, shows=(Enum,)):
    pass


class QtOptionalEditor(OptionalEditing, ControlConstruction, QtValueEditor, QWidget, metaclass=PyQtWidgetMeta, shows=(Optional,)):

    def control_arguments(self) -> dict[str, object]:
        return {}

    def bind_control(self) -> None:
        self._checkbox = QCheckBox("Set", self)
        self._member_editor = QtValueEditor.declared_for(self.field.member)
        layout = QVBoxLayout(self)
        layout.addWidget(self._checkbox)
        layout.addWidget(self._member_editor)
        self._member_editor.setVisible(self.field.value is not None)
        self._checkbox.setChecked(self.field.value is not None)
        self._checkbox.toggled.connect(self._on_held_changed)
        self._member_editor.feedback_changed.connect(self.display_feedback)

    @property
    def member_editor(self) -> QtValueEditor:
        return self._member_editor

    def set_member_shown(self, held: bool) -> None:
        self._member_editor.setVisible(held)

    def paint_held(self, held: bool) -> None:
        self._checkbox.blockSignals(True)
        self._checkbox.setChecked(held)
        self._checkbox.blockSignals(False)

    def _on_held_changed(self, checked: bool) -> None:
        self.change_held(checked)

    def paint(self) -> None:
        held = self.field.value is not None
        self.paint_held(held)
        self._member_editor.setVisible(held)
        if held:
            self._member_editor.paint()
