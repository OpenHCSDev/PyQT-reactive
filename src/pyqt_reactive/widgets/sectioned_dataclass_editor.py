"""Editor for one dataclass value whose child fields render as titled sections.

A subclass declares its value type and its sections. Everything else is
supplied here by four bases, one per concern, because each concern has
consumers the others lack:

* :class:`EditsRawDisplayValue`: the edited value, the shown value, and the
  change signal;
* :class:`ShowsFieldSections`: building sections and answering a form's
  questions about child fields;
* :class:`HasEnableTitleCheckbox`: the enable checkbox in a group-box title;
* :class:`SectionedDataclassEditor`: the widget that joins them.

Section kinds are a family (:class:`EditorSection`). The editor never asks
which kind a section is; it calls ``build`` and keeps what comes back.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar, cast

from formbridge.forms.layout_constants import CURRENT_LAYOUT
from formbridge.forms.raw_display_value import RawDisplayValue
from formbridge.theming.scope_color_receiver import ScopeColorSchemeReceiver
from objectstate import (
    DottedFieldPath,
    ObjectStateSubfieldSemanticIndex,
    StructuralValuePath,
)
from PyQt6.QtCore import QSignalBlocker, pyqtSignal
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from python_introspect import Enableable, is_enableable

from pyqt_reactive.forms.inline_dataclass_chrome import (
    ChildFieldChrome,
    InlineDataclassChildChrome,
    StandaloneChildChrome,
)
from pyqt_reactive.forms.inline_dataclass_context import (
    InlineDataclassChildFieldIdentity,
    InlineDataclassFormContext,
)
from pyqt_reactive.forms.widget_creation_config import EnabledTitleWidgetMoveAuthority
from pyqt_reactive.protocols import (
    ChangeSignalEmitter,
    ChildFieldChromeRefreshable,
    ChildFieldIdentityProvider,
    ChildFieldNavigationTargetProvider,
    ChildFieldSemanticChromeRefreshable,
    ChildSubfieldNavigationTargetProvider,
    InlineDataclassGroupBoxChromeProvider,
    InlineDataclassRootResettable,
    PyQtWidgetMeta,
    RawResolvedValueSettable,
    ResolvedValuePreviewSettable,
    ValueGettable,
    ValueSettable,
)
from pyqt_reactive.widgets.editable_table import (
    DataclassFieldColumns,
    EditableTableController,
    EditableTableLayout,
    RowSuggestionMap,
)
from pyqt_reactive.widgets.no_scroll_spinbox import InheritedCheckBox
from pyqt_reactive.widgets.shared.abstract_table_browser import ColumnDef
from pyqt_reactive.widgets.shared.clickable_help_components import InlineDataclassGroupBox
from pyqt_reactive.widgets.shared.scoped_table_widget import ScopedTableWidget
from pyqt_reactive.widgets.structural_table import (
    EditableTableSemanticBinding,
    IsomorphicDataclassRowPathPolicy,
    StructuralDescendantMaskTarget,
    StructuralFlashTarget,
    StructuralMaskedContainerTarget,
    StructuralWidgetTarget,
)

# --- What a built section leaves behind --------------------------------------


@dataclass(slots=True)
class RenderedSection:
    """The widgets one section built."""

    group: QWidget

    def add_to(self, by_field: dict[str, RenderedFieldSection]) -> None:
        """Enter this section under the field it edits, if it edits one."""


@dataclass(slots=True, kw_only=True)
class RenderedFieldSection(RenderedSection):
    """The widgets of a section that shows one child field in a table."""

    section: FieldSection
    table: QTableWidget
    placeholder_styled: bool = False

    def __post_init__(self) -> None:
        EditableTableController.apply_placeholder_text_style_to_table(self.table, False)

    def add_to(self, by_field: dict[str, RenderedFieldSection]) -> None:
        by_field[self.section.field_name] = self

    def style_placeholder(self, active: bool) -> None:
        """Draw the table as an inherited value (``active``) or a declared one."""

        if self.placeholder_styled is active:
            return
        EditableTableController.apply_placeholder_text_style_to_table(self.table, active)
        self.placeholder_styled = active

    def show_alone(self, value: RawDisplayValue) -> bool:
        """Show a new field value without rebuilding other sections, if possible."""

        return False

    @property
    def addresses_cells(self) -> bool:
        """Whether single cells have ObjectState paths below the field."""

        return False

    def apply_semantic_index(self, semantic_index: ObjectStateSubfieldSemanticIndex) -> None:
        """Mark cells from ObjectState's per-path semantics."""

    def cell_target(self, relative_path: StructuralValuePath) -> StructuralFlashTarget | None:
        """The cell at one ObjectState path below the field."""

        return None

    def settle(self) -> None:
        """Ignore change callbacks still queued from building the section."""


@dataclass(slots=True, kw_only=True)
class RenderedRowTable(RenderedFieldSection):
    """The widgets of a section that edits typed rows."""

    controller: EditableTableController

    def show_alone(self, value: RawDisplayValue) -> bool:
        section = cast(RowTableSection, self.section)
        if not section.refreshes_alone:
            return False
        if self.controller.replace_all(section.rows_of(value.display_field(section.field_name))):
            EditableTableLayout.fit_to_rows(self.table)
        return True

    @property
    def addresses_cells(self) -> bool:
        return self.controller.semantic_binding is not None

    def apply_semantic_index(self, semantic_index: ObjectStateSubfieldSemanticIndex) -> None:
        if self.addresses_cells:
            self.controller.apply_semantic_index(semantic_index)

    def cell_target(self, relative_path: StructuralValuePath) -> StructuralFlashTarget | None:
        if not self.addresses_cells:
            return None
        return self.controller.cell_target_for_semantic_path(relative_path)

    def settle(self) -> None:
        self.controller.suppress_current_rows_until_idle()


# --- Section declarations ----------------------------------------------------


class EditorSection(ABC):
    """One titled block of a sectioned editor. Each member builds itself."""

    title: str

    @abstractmethod
    def build(self, editor: SectionedDataclassEditor) -> RenderedSection:
        """Create this section's widgets inside ``editor``."""

    @staticmethod
    def new_group() -> tuple[QGroupBox, QVBoxLayout]:
        group = QGroupBox("")
        group.setStyleSheet("QGroupBox { margin-top: 6px; }")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)
        return group, layout

    @staticmethod
    def fill(
        table: QTableWidget,
        columns: tuple[ColumnDef, ...],
        rows: tuple[object, ...],
    ) -> None:
        """Fill a read-only table, each cell from its column, and size it to its rows."""

        table.setHorizontalHeaderLabels([column.name for column in columns])
        for row_index, row in enumerate(rows):
            for column_index, column in enumerate(columns):
                table.setItem(row_index, column_index, QTableWidgetItem(column.text_of(row)))
        EditorSection.fit(table)

    @staticmethod
    def fit(table: QTableWidget) -> None:
        table.resizeColumnsToContents()
        EditableTableLayout.configure(table)
        EditableTableLayout.fit_to_rows(table)

    @staticmethod
    def button_row(
        layout: QVBoxLayout,
        *buttons: tuple[str, Callable[[], None]],
    ) -> None:
        """Add a left-aligned row of compact buttons, each bound to its action."""

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        for text, action in buttons:
            button = QPushButton(text)
            button.setFixedHeight(min(CURRENT_LAYOUT.button_height, 24))
            button.clicked.connect(lambda _checked=False, run=action: run())
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)


@dataclass(frozen=True, kw_only=True)
class ReadOnlyTableSection(EditorSection):
    """A table that shows records the declaring editor supplies; nothing is edited.

    Each column says what it shows of a row, so headers and cells cannot drift.
    """

    title: str
    columns: tuple[ColumnDef, ...]
    rows: tuple[object, ...]

    def build(self, editor: SectionedDataclassEditor) -> RenderedSection:
        group, layout = self.new_group()
        ChildFieldChrome.add_plain_header(layout, group, self.title)
        table = editor.new_table(len(self.rows), len(self.columns))
        self.fill(table, self.columns, self.rows)
        layout.addWidget(table)
        return RenderedSection(group)


@dataclass(frozen=True, kw_only=True)
class FieldSection(EditorSection):
    """A section that shows one child field of the edited dataclass."""

    title: str
    field_name: str

    def shown(self, value: RawDisplayValue) -> object:
        """What this section renders from; two equal results render the same."""

        return value.display_field(self.field_name)

    def field_group(self, editor: SectionedDataclassEditor) -> tuple[QGroupBox, QVBoxLayout]:
        """A group whose header is this field's label, reset button and markers."""

        group, layout = self.new_group()
        editor.chrome.add_section_header(layout, group, self.title, self.field_name)
        return group, layout


@dataclass(frozen=True, kw_only=True)
class TupleSummarySection(FieldSection):
    """A tuple field shown as a read-only summary, edited through its actions.

    For records too wide for an inline row table: the declaring editor
    supplies the summary rows, the columns that show them and the buttons
    that edit the field.
    """

    columns: tuple[ColumnDef, ...]
    rows: tuple[object, ...]
    actions: tuple[tuple[str, Callable[[], None]], ...]

    def shown(self, value: RawDisplayValue) -> object:
        return tuple(cast(tuple, value.display_field(self.field_name)) or ())

    def build(self, editor: SectionedDataclassEditor) -> RenderedFieldSection:
        group, layout = self.field_group(editor)
        table = editor.new_table(len(self.rows), len(self.columns))
        self.fill(table, self.columns, self.rows)
        layout.addWidget(table)
        self.button_row(layout, *self.actions)
        return RenderedFieldSection(group=group, section=self, table=table)


@dataclass(frozen=True, kw_only=True)
class RowTableSection(FieldSection):
    """A section that edits a field through a table of typed rows.

    ``row_type`` is a dataclass; its fields are the columns and each cell's
    editor comes from the field's type (``DataclassFieldColumns``). A row type
    whose field is a family of registered classes therefore offers every
    registered member, including ones registered later.

    Members say how the field value maps to rows and back.
    """

    row_type: type
    new_row: Callable[[], object]
    add_label: str
    remove_label: str = "Remove selected"
    refreshes_alone: bool = False
    """A changed value of this field re-renders only this table. Declare it
    only when no other section is computed from the field."""

    @abstractmethod
    def rows_of(self, field_value: object) -> tuple:
        """The rows that show ``field_value``."""

    @abstractmethod
    def value_of(self, rows: tuple, value: RawDisplayValue) -> object:
        """The field value the rows declare."""

    def rows_complete(self, rows: tuple) -> bool:
        """Whether the rows can be written back yet."""

        return True

    def semantic_binding(
        self,
        columns: DataclassFieldColumns,
    ) -> EditableTableSemanticBinding | None:
        """How cells map to ObjectState paths below the field; none by default."""

        return None

    def build(self, editor: SectionedDataclassEditor) -> RenderedRowTable:
        group, layout = self.field_group(editor)
        columns = DataclassFieldColumns.of(self.row_type)
        table = editor.new_table(0, len(columns))
        table.setHorizontalHeaderLabels(columns.labels)
        columns.apply_header_items(table.horizontalHeaderItem)
        field_name = self.field_name
        controller = EditableTableController(
            table=table,
            columns=columns,
            apply_changes=lambda: editor.apply_rows(field_name),
            suggestions=editor.suggestions(),
            semantic_binding=self.semantic_binding(columns),
        )
        with controller.update_guard:
            for row in self.rows_of(editor.shown.display_field(field_name)):
                controller.append(row)
        table.itemChanged.connect(lambda _: controller.request_apply_changes())
        self.fit(table)
        layout.addWidget(table)
        self.button_row(
            layout,
            (self.add_label, lambda: editor.add_new_row(field_name)),
            (self.remove_label, lambda: editor.remove_selected_rows(field_name)),
        )
        return RenderedRowTable(group=group, section=self, table=table, controller=controller)


@dataclass(frozen=True, kw_only=True)
class TupleFieldSection(RowTableSection):
    """A row table over a field that is a tuple of ``row_type`` values.

    Row ``i``, column ``c`` is the value at ``field[i].<column path>``, so
    ObjectState can address single cells.
    """

    def shown(self, value: RawDisplayValue) -> object:
        return self.rows_of(value.display_field(self.field_name))

    def rows_of(self, field_value: object) -> tuple:
        return tuple(cast(tuple, field_value) or ())

    def value_of(self, rows: tuple, value: RawDisplayValue) -> object:
        return rows

    def semantic_binding(
        self,
        columns: DataclassFieldColumns,
    ) -> EditableTableSemanticBinding | None:
        return EditableTableSemanticBinding(
            owner_field_name=self.field_name,
            row_path_policy=IsomorphicDataclassRowPathPolicy(
                row_value_type=self.row_type,
                column_count=len(columns),
            ),
        )


# --- The enable checkbox in a group-box title --------------------------------


class TitleCheckbox(ABC):
    """The enable checkbox of an editor's group box: attached, or not yet."""

    __slots__ = ()

    @abstractmethod
    def attached_to(
        self,
        groupbox: InlineDataclassGroupBox,
        *,
        tooltip: str,
        on_toggled: Callable[[bool], None],
        on_reset: Callable[[], None],
        provenance_button: QWidget | None,
    ) -> AttachedTitleCheckbox:
        """The checkbox in ``groupbox``'s title, created on first use."""

    @abstractmethod
    def show(self, raw_enabled: bool | None, effective_enabled: bool) -> None:
        """Show the declared state, or the inherited one when none is declared."""

    @abstractmethod
    def style_reset(self, chrome: ChildFieldChrome, field_name: str) -> None:
        """Restyle the reset button from the field's state."""

    @abstractmethod
    def flash_target(self) -> StructuralFlashTarget | None:
        """What a form flashes when the enable field changes."""


class NoTitleCheckbox(TitleCheckbox):
    """No group box has asked for the checkbox yet."""

    __slots__ = ()

    def attached_to(
        self,
        groupbox: InlineDataclassGroupBox,
        *,
        tooltip: str,
        on_toggled: Callable[[bool], None],
        on_reset: Callable[[], None],
        provenance_button: QWidget | None,
    ) -> AttachedTitleCheckbox:
        title_row = EnabledTitleWidgetMoveAuthority()
        checkbox = InheritedCheckBox(groupbox)
        checkbox.setToolTip(tooltip)
        checkbox.toggled.connect(lambda checked: on_toggled(bool(checked)))
        title_widget = title_row.wrap_checkbox_widget_for_title(checkbox, groupbox.color_scheme)
        title_row.bind_title_label_to_checkbox(groupbox, checkbox)
        reset_button = QPushButton("Reset", groupbox)
        reset_button.setToolTip("Reset enabled to default")
        title_row.prepare_title_reset_button(reset_button, groupbox.color_scheme)
        reset_button.clicked.connect(lambda _checked=False: on_reset())
        groupbox.addEnableableWidgets(title_widget, reset_button, provenance_button)
        return AttachedTitleCheckbox(
            groupbox=groupbox,
            checkbox=checkbox,
            title_widget=title_widget,
            reset_button=reset_button,
            provenance_button=provenance_button,
        )

    def show(self, raw_enabled: bool | None, effective_enabled: bool) -> None:
        return

    def style_reset(self, chrome: ChildFieldChrome, field_name: str) -> None:
        return

    def flash_target(self) -> StructuralFlashTarget | None:
        return None


@dataclass(slots=True)
class AttachedTitleCheckbox(TitleCheckbox):
    """The checkbox, its reset button and its provenance button in one title row."""

    groupbox: InlineDataclassGroupBox
    checkbox: InheritedCheckBox
    title_widget: QWidget
    reset_button: QPushButton
    provenance_button: QWidget | None

    def attached_to(
        self,
        groupbox: InlineDataclassGroupBox,
        *,
        tooltip: str,
        on_toggled: Callable[[bool], None],
        on_reset: Callable[[], None],
        provenance_button: QWidget | None,
    ) -> AttachedTitleCheckbox:
        return self

    def show(self, raw_enabled: bool | None, effective_enabled: bool) -> None:
        blocker = QSignalBlocker(self.checkbox)
        try:
            self.checkbox.set_value(raw_enabled)
            if raw_enabled is None:
                self.checkbox.set_placeholder_preview(effective_enabled)
        finally:
            blocker.unblock()

    def style_reset(self, chrome: ChildFieldChrome, field_name: str) -> None:
        chrome.style_reset_button(self.reset_button, field_name)

    def flash_target(self) -> StructuralFlashTarget | None:
        return EnabledTitleWidgetMoveAuthority.title_field_flash_target(
            container=self.groupbox,
            title_widget=self.title_widget,
            checkbox_widget=self.checkbox,
            reset_button=self.reset_button,
            provenance_button=self.provenance_button,
        )


# --- The editor's three concerns ---------------------------------------------


class EditsRawDisplayValue(
    ValueGettable,
    ValueSettable,
    ResolvedValuePreviewSettable,
    RawResolvedValueSettable,
    ChangeSignalEmitter,
):
    """Hold the edited and the shown value; a subclass says how to render one.

    State, set by the widget's ``__init__``: ``_value`` and ``_change_callbacks``.
    """

    _value: RawDisplayValue
    _change_callbacks: dict[Callable[[object], None], Callable[[], None]]

    @abstractmethod
    def show_value(self, incoming: RawDisplayValue) -> None:
        """Take ``incoming`` as the current value and render it."""

    @property
    def shown(self) -> RawDisplayValue:
        """The edited value together with the value on screen."""

        return self._value

    @property
    def value(self) -> object:
        """Value property used by pyqt-reactive signal adapters."""

        return self._value.raw

    def get_value(self) -> object:
        return self._value.raw

    def _raw_or_empty(self, raw: object | None) -> object:
        return raw if raw is not None else type(self._value.raw)()

    def set_value(self, value: object | None) -> None:
        self.show_value(
            RawDisplayValue.shown_as_edited(self._value.value_type, self._raw_or_empty(value))
        )

    def set_resolved_value_preview(self, value: object) -> None:
        """Change the inherited values on screen without changing the edit value."""

        self.show_value(self._value.displaying(value))

    def set_raw_value_with_resolved_preview(
        self,
        raw_value: object | None,
        resolved_value: object | None,
    ) -> None:
        raw = self._raw_or_empty(raw_value)
        incoming = RawDisplayValue(
            self._value.value_type,
            raw,
            resolved_value if resolved_value is not None else raw,
        )
        if incoming != self._value:
            self.show_value(incoming)

    def connect_change_signal(self, callback: Callable[[object], None]) -> None:
        def emit_value() -> None:
            callback(self.get_value())

        self._change_callbacks[callback] = emit_value
        self.changed.connect(emit_value)

    def disconnect_change_signal(self, callback: Callable[[object], None]) -> None:
        if callback in self._change_callbacks:
            self.changed.disconnect(self._change_callbacks.pop(callback))


class ShowsFieldSections(
    ChildFieldChromeRefreshable,
    ChildFieldIdentityProvider,
    ChildFieldNavigationTargetProvider,
    ChildFieldSemanticChromeRefreshable,
    ChildSubfieldNavigationTargetProvider,
    InlineDataclassRootResettable,
):
    """Build declared sections and answer a form's questions about child fields.

    State, set by the widget's ``__init__``: ``chrome`` (in a form or
    standalone), ``_rendered`` (the field sections on screen, by field name)
    and ``sections_layout``.
    """

    chrome: ChildFieldChrome
    _rendered: dict[str, RenderedFieldSection]
    sections_layout: QVBoxLayout

    @abstractmethod
    def sections(self) -> tuple[EditorSection, ...]:
        """The sections to show for the current value, top to bottom."""

    def suggestions(self) -> RowSuggestionMap:
        """Picker suggestions per row type; none unless a subclass has some."""

        return MappingProxyType({})

    def rendered(self, field_name: str) -> RenderedFieldSection:
        """The widgets of the section that shows ``field_name``."""

        return self._rendered[field_name]

    def table(self, field_name: str) -> QTableWidget:
        return self._rendered[field_name].table

    def row_table(self, field_name: str) -> RenderedRowTable:
        return cast(RenderedRowTable, self._rendered[field_name])

    def refresh(self) -> None:
        """Rebuild every section from the current value."""

        while self.sections_layout.count():
            widget = self.sections_layout.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._rendered = {}
        self.chrome = self.chrome.emptied()
        for section in self.sections():
            rendered = section.build(cast("SectionedDataclassEditor", self))
            self.sections_layout.addWidget(rendered.group)
            rendered.add_to(self._rendered)
        self.sections_layout.addStretch(1)
        self.refresh_child_field_chrome()
        for rendered_field in self._rendered.values():
            rendered_field.settle()

    def _form_chrome(self) -> InlineDataclassChildChrome:
        if not isinstance(self.chrome, InlineDataclassChildChrome):
            raise RuntimeError(f"{type(self).__name__} child fields require a form.")
        return self.chrome

    def child_field_identity(self, field_name: str) -> InlineDataclassChildFieldIdentity:
        return self._form_chrome().child_identity(field_name)

    def child_field_label(self, field_name: str):
        chrome = self._form_chrome()
        return chrome.labels[chrome.child_identity(field_name)]

    def child_field_reset_button(self, field_name: str) -> QPushButton:
        chrome = self._form_chrome()
        return chrome.reset_buttons[chrome.child_identity(field_name)]

    def child_field_navigation_target(self, field_name: str) -> QWidget | None:
        return self.chrome.navigation_target(field_name)

    def child_field_section_group(self, field_name: str) -> QWidget:
        target = self.child_field_navigation_target(field_name)
        if target is None:
            raise RuntimeError(f"Child section {field_name!r} is not rendered.")
        return target

    def reset_inline_dataclass_fields(self) -> None:
        self.chrome.reset_children()

    def child_field_semantic_owner_paths(self) -> tuple[DottedFieldPath, ...]:
        return self.chrome.child_paths(
            name for name, rendered in self._rendered.items() if rendered.addresses_cells
        )

    def refresh_child_field_semantics(
        self,
        owner_field_path: DottedFieldPath,
        semantic_index: ObjectStateSubfieldSemanticIndex,
    ) -> None:
        for name in self.chrome.field_names_under((owner_field_path,)):
            if name in self._rendered:
                self._rendered[name].apply_semantic_index(semantic_index)

    def _section_target(
        self,
        child_identity: InlineDataclassChildFieldIdentity,
        relative_path: StructuralValuePath,
    ) -> StructuralFlashTarget | None:
        """The section, or one of its cells, that a form flashes and scrolls to."""

        field_name = child_identity.field_name
        group = self.child_field_navigation_target(field_name)
        if group is None:
            return None
        label = self.child_field_label(field_name)
        if not relative_path.segments:
            return StructuralMaskedContainerTarget(
                container=cast(QWidget, self),
                masked_target=StructuralDescendantMaskTarget(group),
                label_widget=label,
                scroll_target=StructuralWidgetTarget(label),
            )
        cell = self._rendered[field_name].cell_target(relative_path)
        if cell is None:
            return None
        return StructuralMaskedContainerTarget(
            container=group,
            masked_target=cell,
            label_widget=label,
        )


class HasEnableTitleCheckbox(InlineDataclassGroupBoxChromeProvider):
    """Put an ``Enableable`` value's enable field in the group-box title.

    State, set by the widget's ``__init__``: ``title_checkbox``. Reads
    ``_value`` and ``chrome``, which the other two bases own.
    """

    enable_tooltip: ClassVar[str] = "Enable"
    title_checkbox: TitleCheckbox

    def _is_enableable(self) -> bool:
        return is_enableable(self._value.declared_type)

    def configure_inline_dataclass_groupbox(self, groupbox: InlineDataclassGroupBox) -> None:
        if not self._is_enableable():
            return
        enabled_field = Enableable.require_parameter_name()
        self.title_checkbox = self.title_checkbox.attached_to(
            groupbox,
            tooltip=self.enable_tooltip,
            on_toggled=self._set_enabled,
            on_reset=lambda: self.chrome.reset_child(enabled_field),
            provenance_button=self.chrome.provenance_button(enabled_field, groupbox.color_scheme),
        )
        self._show_enabled()

    def _show_enabled(self) -> None:
        """Show the enable state in the title and dim a disabled editor."""

        widget = cast(QWidget, self)
        if not self._is_enableable():
            InlineDataclassChildChrome.set_widget_dimmed(widget, False)
            return
        raw_enabled = cast(Enableable, self._value.raw).enabled
        effective_enabled = bool(cast(Enableable, self._value.display).enabled)
        self.title_checkbox.show(
            None if raw_enabled is None else bool(raw_enabled),
            effective_enabled,
        )
        self.title_checkbox.style_reset(self.chrome, Enableable.require_parameter_name())
        InlineDataclassChildChrome.set_widget_dimmed(widget, not effective_enabled, 0.4)

    def _set_enabled(self, enabled: bool) -> None:
        self._value = self._value.replacing(**{Enableable.require_parameter_name(): enabled})
        self._show_enabled()
        self.changed.emit()


# --- The widget --------------------------------------------------------------


class SectionedDataclassEditor(
    QWidget,
    EditsRawDisplayValue,
    ShowsFieldSections,
    HasEnableTitleCheckbox,
    ScopeColorSchemeReceiver,
    metaclass=PyQtWidgetMeta,
):
    """Inline form widget that edits one dataclass value section by section.

    A subclass sets ``value_type`` and implements :meth:`sections`.
    """

    value_type: ClassVar[type]
    changed = pyqtSignal()

    def __init__(
        self,
        value: RawDisplayValue,
        *,
        form_context: InlineDataclassFormContext | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._value = value
        self._change_callbacks = {}
        self.chrome = (
            StandaloneChildChrome(self._reset_field_to_default)
            if form_context is None
            else InlineDataclassChildChrome(form_context)
        )
        self._rendered = {}
        self.title_checkbox = NoTitleCheckbox()
        self._scope_color_scheme = None
        self.sections_layout = QVBoxLayout(self)
        self.sections_layout.setContentsMargins(0, 0, 0, 0)
        self.sections_layout.setSpacing(3)
        self.refresh()

    @classmethod
    def for_value(cls, raw: object, **context) -> SectionedDataclassEditor:
        """An editor that shows ``raw`` exactly as edited (nothing inherited)."""

        return cls(RawDisplayValue.shown_as_edited(cls.value_type, raw), **context)

    @classmethod
    def in_form(
        cls,
        *,
        current_value: object,
        manager,
        param_info,
        parent: QWidget | None = None,
        **_: object,
    ) -> SectionedDataclassEditor:
        """Inline dataclass widget factory: the editor as a child of a form.

        The shown value is the form state's resolved value, so inherited
        fields appear as placeholders.
        """

        context = InlineDataclassFormContext.from_inline_widget(
            manager=manager,
            param_info=param_info,
            current_value=current_value,
        )
        resolved = DottedFieldPath(context.owner_path.value).bind(context.state).value
        return cls(
            RawDisplayValue(
                cls.value_type,
                current_value,
                current_value if resolved is None else resolved,
            ),
            form_context=context,
            parent=parent,
        )

    # -- rendering an incoming value

    def _enabled_shown(self, value: RawDisplayValue) -> object:
        if not self._is_enableable():
            return None
        return value.display_field(Enableable.require_parameter_name())

    def show_value(self, incoming: RawDisplayValue) -> None:
        """Render ``incoming`` with the smallest update that shows it."""

        from objectstate.time_travel_profile import TimeTravelProfiler

        with TimeTravelProfiler.phase(
            "sectioned_dataclass_editor.show_value",
            widget=type(self).__qualname__,
        ):
            current = self._value
            self._value = incoming
            changed = tuple(
                name
                for name, rendered in self._rendered.items()
                if rendered.section.shown(current) != rendered.section.shown(incoming)
            )
            if not changed:
                if incoming.raw == current.raw and self._enabled_shown(
                    incoming
                ) == self._enabled_shown(current):
                    self.refresh_child_field_chrome()
                    return
                if self._is_enableable():
                    self._show_enabled()
                    self._refresh_field_chrome(Enableable.require_parameter_name())
                    return
            if len(changed) == 1 and self._rendered[changed[0]].show_alone(incoming):
                self._refresh_field_chrome(changed[0])
                return
            self.refresh()

    # -- markers

    def refresh_child_field_chrome(
        self,
        owner_field_paths: tuple[DottedFieldPath, ...] | None = None,
    ) -> None:
        """Redraw labels, reset buttons, inherited styling and the enable state."""

        from objectstate.time_travel_profile import TimeTravelProfiler

        with TimeTravelProfiler.phase("sectioned_dataclass_editor.refresh_child_field_chrome"):
            enabled_field = Enableable.require_parameter_name()
            if owner_field_paths is None:
                self.chrome.refresh_markers()
                field_names = (*self._rendered, enabled_field)
            else:
                field_names = self.chrome.field_names_under(owner_field_paths)
                self.chrome.refresh_markers(field_names)
            for name in field_names:
                if name in self._rendered:
                    self._style_inherited(name)
            if enabled_field in field_names:
                self._show_enabled()

    def _refresh_field_chrome(self, field_name: str) -> None:
        paths = self.chrome.child_paths((field_name,))
        self.refresh_child_field_chrome(paths or None)

    def _style_inherited(self, field_name: str) -> None:
        inherited = self.chrome.has_inherited_preview(
            field_name
        ) or self._value.shows_inherited(field_name)
        group = self.chrome.navigation_target(field_name)
        if inherited and group is not None:
            InlineDataclassChildChrome.set_widget_dimmed(group, False)
        self._rendered[field_name].style_placeholder(inherited)

    def child_subfield_navigation_target(
        self,
        child_identity: InlineDataclassChildFieldIdentity,
        relative_path: StructuralValuePath,
    ) -> StructuralFlashTarget | None:
        if (
            child_identity.field_name == Enableable.require_parameter_name()
            and not relative_path.segments
        ):
            return self.title_checkbox.flash_target()
        return self._section_target(child_identity, relative_path)

    # -- edits

    def edit_field(self, field_name: str, field_value: object) -> None:
        """Write one field from a section whose own widgets already show it."""

        self._value = self._value.replacing(**{field_name: field_value})
        self.changed.emit()

    def replace_field(self, field_name: str, field_value: object) -> None:
        """Write one field and rebuild every section from the new value."""

        self._value = self._value.replacing(**{field_name: field_value})
        self.refresh()
        self.changed.emit()

    def append_to_field(self, field_name: str, item: object) -> None:
        """Append one item to a tuple field, declaring any inherited items."""

        shown = cast(tuple, self._value.display_field(field_name)) or ()
        self.replace_field(field_name, (*shown, item))

    def _reset_field_to_default(self, field_name: str) -> None:
        self.replace_field(field_name, self._value.field_default(field_name))

    def apply_rows(self, field_name: str) -> None:
        """Write a row table back to its field once every row is complete."""

        rendered = self.row_table(field_name)
        section = cast(RowTableSection, rendered.section)
        if rendered.controller.has_incomplete_rows():
            return
        rows = rendered.controller.rows()
        if not section.rows_complete(rows):
            return
        self.edit_field(field_name, section.value_of(rows, self._value))

    def add_row(self, field_name: str, row: object) -> None:
        rendered = self.row_table(field_name)
        with rendered.controller.update_guard:
            rendered.controller.append(row)
        EditableTableLayout.fit_to_rows(rendered.table)
        self.apply_rows(field_name)

    def add_new_row(self, field_name: str) -> None:
        """Append the row the section declares for a new entry."""

        self.add_row(field_name, cast(RowTableSection, self.rendered(field_name).section).new_row())

    def remove_selected_rows(self, field_name: str) -> None:
        rendered = self.row_table(field_name)
        if not rendered.controller.remove_selected():
            return
        EditableTableLayout.fit_to_rows(rendered.table)
        self.apply_rows(field_name)

    # -- tables

    def new_table(self, rows: int, columns: int) -> ScopedTableWidget:
        table = ScopedTableWidget(rows, columns)
        table.set_scope_color_scheme(self._scope_color_scheme)
        return table

    def set_scope_color_scheme(self, scheme) -> None:
        self._scope_color_scheme = scheme
        for table in self.findChildren(ScopedTableWidget):
            table.set_scope_color_scheme(scheme)
            EditableTableLayout.fit_to_rows(table)


__all__ = (
    "AttachedTitleCheckbox",
    "EditorSection",
    "EditsRawDisplayValue",
    "FieldSection",
    "HasEnableTitleCheckbox",
    "NoTitleCheckbox",
    "ReadOnlyTableSection",
    "RenderedFieldSection",
    "RenderedRowTable",
    "RenderedSection",
    "RowTableSection",
    "SectionedDataclassEditor",
    "ShowsFieldSections",
    "TitleCheckbox",
    "TupleFieldSection",
    "TupleSummarySection",
)
