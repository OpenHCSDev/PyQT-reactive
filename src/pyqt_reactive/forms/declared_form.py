"""A form over one ObjectState's fields, edited by the declared editor family.

The Qt counterpart of a Formbridge form view: FollowingForm follows the state and
repaints editors, each value row holds the editor ``QtValueEditor.declared_for``
chooses for its DeclaredField, and a nested dataclass field is a titled group of
its own rows. Which rows a state shows is ParameterFormService's answer, the same
one every other frontend reads.
"""

from __future__ import annotations

from collections.abc import Iterator

from formbridge.forms.declared_fields import DeclaredField, DeclaredViews
from formbridge.forms.form_following import FollowedFieldView, FollowedValueView, FollowingForm
from formbridge.forms.parameter_form_service import ParameterFormService
from formbridge.forms.parameter_info_types import DirectDataclassInfo, ParameterInfo
from formbridge.forms.value_editing import ValueEditing
from objectstate import DottedFieldPath, ObjectState
from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout, QWidget

from pyqt_reactive.forms.declared_editors import QtValueEditor
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.theming import ColorScheme, StatusColorRole
from pyqt_reactive.widgets.status_line import NoticeLine


class DeclaredPart(FollowedFieldView, DeclaredViews):
    """One part of a declared form; the kind of field it shows chooses the member."""

    @classmethod
    def of(cls, state: ObjectState, parent: str, color_scheme: ColorScheme) -> list[DeclaredPart]:
        return [cls.showing(type(parameter).__mro__)(DeclaredField(state, path), color_scheme)
                for path, parameter in ParameterFormService().parameters_for_state(state, parent)]


class DeclaredRow(DeclaredPart, FollowedValueView, QWidget, metaclass=PyQtWidgetMeta, shows=(ParameterInfo,)):
    """A field with one value: its label over its editor, and the editor's refusal under it,
    kept for as long as the editor holds the refused text."""

    changed_mark = " ●"

    def __init__(self, field: DeclaredField, color_scheme: ColorScheme) -> None:
        super().__init__()
        self.field = field
        self.editor = QtValueEditor.declared_for(field)
        self.label = QLabel(field.label)
        self.label.setWordWrap(True)
        self.label.setToolTip(field.help)
        self.feedback = NoticeLine(color_scheme)
        self.editor.feedback_changed.connect(self.show_feedback)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)
        layout.addWidget(self.editor)
        layout.addWidget(self.feedback)

    def mark(self, changed: bool) -> None:
        self.label.setText(self.field.label + (self.changed_mark if changed else ""))

    def show_feedback(self, text: str) -> None:
        self.feedback.show_status(text, StatusColorRole.ERROR)
        self.feedback.setVisible(bool(text))

    @property
    def refused(self) -> bool:
        """Whether the editor is holding a refusal of what was typed."""
        return bool(self.feedback.text())


class DeclaredGroup(DeclaredPart, QGroupBox, metaclass=PyQtWidgetMeta, shows=(DirectDataclassInfo,)):
    """A nested dataclass field: its title over the rows of its own fields."""

    def __init__(self, field: DeclaredField, color_scheme: ColorScheme) -> None:
        super().__init__(field.label)
        self.field = field
        self.setToolTip(field.help)
        self.parts = DeclaredPart.of(field.state, field.path.value, color_scheme)
        layout = QVBoxLayout(self)
        for part in self.parts:
            layout.addWidget(part)

    def values(self) -> Iterator[FollowedValueView]:
        for part in self.parts:
            yield from part.values()

    def filter(self, term: str) -> bool:
        shown = [part.filter(term) for part in self.parts]
        self.setVisible(any(shown))
        return any(shown)


class DeclaredForm(FollowingForm, QWidget):
    """Every shown field of one ObjectState, followed while the form is open.

    The form follows its state from construction; whoever closes it calls
    ``leave_state`` first, so no late change paints a closed form.
    """

    def __init__(self, state: ObjectState, color_scheme: ColorScheme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self.parts = DeclaredPart.of(state, "", color_scheme)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for part in self.parts:
            layout.addWidget(part)
        self.build_index()
        self.follow_state()

    def repaint_editor(self, editor: ValueEditing) -> None:
        editor.paint()

    def editor(self, path: DottedFieldPath) -> QtValueEditor:
        return self.values[path.value].editor

    @property
    def refused(self) -> bool:
        """Whether any editor is showing a refusal of what was typed."""
        return any(row.refused for row in self.values.values())
