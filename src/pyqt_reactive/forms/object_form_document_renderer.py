"""Render one or more ObjectState-backed objects as read-only forms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from pyqt_reactive.theming import ColorScheme

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ObjectFormEntry(Generic[T]):
    """One named object rendered by ObjectFormDocumentRenderer."""

    name: str
    object_instance: T
    summary: str | None = None


@dataclass(frozen=True, slots=True)
class ObjectFormDocument(Generic[T]):
    """A read-only object-form document with one or more selectable entries."""

    title: str
    entries: tuple[ObjectFormEntry[T], ...]
    selector_label: str = "Entry:"

    def __post_init__(self) -> None:
        if not self.entries:
            raise ValueError("ObjectFormDocument requires at least one entry.")


@dataclass(frozen=True, slots=True)
class ObjectFormRenderContext:
    """Rendering context for ObjectState-backed read-only forms."""

    parent: QWidget
    scope_id: str | None = None
    color_scheme: ColorScheme | None = None
    exclude_params: tuple[str, ...] = ()


class ObjectFormDocumentRenderer:
    """Render an ObjectFormDocument into an existing Qt layout."""

    def __init__(self, context: ObjectFormRenderContext) -> None:
        self._context = context

    def render(self, layout: QVBoxLayout, document: ObjectFormDocument[T]) -> None:
        entries = document.entries
        if len(entries) == 1:
            self._add_object_form(layout, entries[0])
            return

        selector_row = QHBoxLayout()
        selector_label = QLabel(document.selector_label)
        selector = QComboBox()
        selector.addItems([entry.name for entry in entries])
        selector_row.addWidget(selector_label)
        selector_row.addWidget(selector, 1)
        layout.addLayout(selector_row)

        form_container = QWidget()
        form_layout = QVBoxLayout(form_container)
        form_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(form_container)

        entries_by_name = {entry.name: entry for entry in entries}

        def render_selected(entry_name: str) -> None:
            _clear_layout(form_layout)
            self._add_object_form(form_layout, entries_by_name[entry_name])

        selector.currentTextChanged.connect(render_selected)
        render_selected(selector.currentText())

    def _add_object_form(
        self,
        layout: QVBoxLayout,
        entry: ObjectFormEntry[T],
    ) -> None:
        from objectstate import ObjectState
        from pyqt_reactive.forms.parameter_form_manager import (
            FormManagerConfig,
            ParameterFormManager,
        )

        if entry.summary:
            layout.addWidget(QLabel(entry.summary))

        state = ObjectState(
            object_instance=entry.object_instance,
            scope_id=self._context.scope_id,
        )
        object_form = ParameterFormManager(
            state=state,
            config=FormManagerConfig(
                parent=self._context.parent,
                read_only=True,
                color_scheme=self._context.color_scheme,
                exclude_params=list(self._context.exclude_params),
            ),
        )
        layout.addWidget(object_form)


def _clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
