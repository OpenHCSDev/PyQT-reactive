"""
Abstract base class for table-based browser widgets.

Provides common infrastructure for widgets that display searchable, filterable
table views of item collections. Subclasses implement the abstract methods
to customize column layout, row population, and event handling.
"""

from abc import abstractmethod
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Generic, List, Optional, TypeVar

from PyQt6.QtCore import QItemSelectionModel, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pyqt_reactive.services.search_service import SearchService
from pyqt_reactive.theming import ColorScheme, StyleSheetGenerator

T = TypeVar('T')

class TableSelectionMode(Enum):
    """Selection cardinality for table browser rows."""

    SINGLE = "single"
    MULTI = "multi"

    @property
    def qt_mode(self) -> QAbstractItemView.SelectionMode:
        if self is TableSelectionMode.MULTI:
            return QAbstractItemView.SelectionMode.ExtendedSelection
        return QAbstractItemView.SelectionMode.SingleSelection


@dataclass(frozen=True)
class ColumnDef:
    """Declarative column configuration for table browsers."""
    name: str
    key: str
    width: Optional[int] = None
    sortable: bool = True
    resizable: bool = True
    filterable: bool = False
    filter_values: Callable[[object], Iterable[object]] | None = None


@dataclass(frozen=True)
class ColumnPresentation:
    """User presentation choices keyed by stable :class:`ColumnDef` identity.

    ``ordered_keys`` is a preference, not an available-column declaration.
    Keys absent from the current declaration are retained so a dynamic column
    can recover its prior position if it reappears. Newly declared columns are
    appended in declaration order.
    """

    ordered_keys: tuple[str, ...] = ()
    hidden_keys: frozenset[str] = frozenset()

    def resolved_keys(self, columns: Sequence[ColumnDef]) -> tuple[str, ...]:
        """Resolve this preference against the current declared columns."""
        declared_keys = tuple(column.key for column in columns)
        declared_key_set = set(declared_keys)
        preferred = tuple(
            key for key in dict.fromkeys(self.ordered_keys) if key in declared_key_set
        )
        preferred_set = set(preferred)
        return preferred + tuple(
            key for key in declared_keys if key not in preferred_set
        )

    def is_visible(self, key: str) -> bool:
        """Return whether ``key`` is visible under this preference."""
        return key not in self.hidden_keys

    def with_resolved_order(
        self,
        ordered_keys: Sequence[str],
        columns: Sequence[ColumnDef],
    ) -> "ColumnPresentation":
        """Replace current-column order while retaining absent dynamic keys."""
        declared_keys = tuple(column.key for column in columns)
        requested_order = tuple(dict.fromkeys(ordered_keys))
        if len(requested_order) != len(declared_keys) or set(
            requested_order
        ) != set(declared_keys):
            raise ValueError(
                "Resolved column order must contain every current ColumnDef.key "
                "exactly once"
            )

        current_keys = set(declared_keys)
        requested_iter = iter(requested_order)
        merged_order: list[str] = []
        for key in self.ordered_keys:
            if key in current_keys:
                replacement = next(requested_iter, None)
                if replacement is not None:
                    merged_order.append(replacement)
            else:
                merged_order.append(key)
        merged_order.extend(requested_iter)
        return ColumnPresentation(tuple(merged_order), self.hidden_keys)


class ColumnPresentationState(QObject):
    """Shared runtime owner for a table and its column-derived projections.

    Persistence is deliberately outside this generic UI owner. Callers may
    inject an initial immutable preference and persist ``preference_changed``
    through their own typed configuration boundary.
    """

    changed = pyqtSignal()
    preference_changed = pyqtSignal(object)

    def __init__(
        self,
        preference: ColumnPresentation | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._columns: tuple[ColumnDef, ...] = ()
        self._preference = self._normalized(preference or ColumnPresentation())

    @staticmethod
    def _normalized(preference: ColumnPresentation) -> ColumnPresentation:
        return ColumnPresentation(
            ordered_keys=tuple(dict.fromkeys(preference.ordered_keys)),
            hidden_keys=frozenset(preference.hidden_keys),
        )

    @property
    def columns(self) -> tuple[ColumnDef, ...]:
        """Return the current authoritative column declarations."""
        return self._columns

    @property
    def preference(self) -> ColumnPresentation:
        """Return the immutable presentation preference."""
        return self._preference

    def set_columns(self, columns: Sequence[ColumnDef]) -> None:
        """Publish the table owner's current column declarations."""
        declared = tuple(columns)
        keys = tuple(column.key for column in declared)
        if len(keys) != len(set(keys)):
            raise ValueError("ColumnDef.key values must be unique")
        if declared == self._columns:
            return
        self._columns = declared
        self.changed.emit()

    def set_preference(self, preference: ColumnPresentation) -> None:
        """Replace presentation choices without changing declarations."""
        normalized = self._normalized(preference)
        if normalized == self._preference:
            return
        self._preference = normalized
        self.preference_changed.emit(normalized)
        self.changed.emit()

    def resolved_keys(self) -> tuple[str, ...]:
        """Return current column keys in resolved presentation order."""
        return self._preference.resolved_keys(self._columns)

    def resolved_columns(self) -> tuple[ColumnDef, ...]:
        """Return current declarations in resolved presentation order."""
        columns_by_key = {column.key: column for column in self._columns}
        return tuple(columns_by_key[key] for key in self.resolved_keys())


class AbstractTableBrowser(QWidget, Generic[T]):
    """
    Abstract base class for table-based browser widgets.

    Provides:
    - Table widget with configurable columns (static or dynamic)
    - Search input with SearchService integration
    - Status label showing item counts
    - Row selection handling (single or multi-select)

    Subclasses must implement abstract methods to customize behavior.
    """

    # Signals for selection events
    item_selected = pyqtSignal(str, object)  # key, item
    item_double_clicked = pyqtSignal(str, object)  # key, item
    items_selected = pyqtSignal(list)  # list of keys (for multi-select)
    column_filter_selection_changed = pyqtSignal(str, object)

    INCREMENTAL_POPULATE_THRESHOLD = 750
    INCREMENTAL_BATCH_SIZE = 200

    def __init__(
        self,
        color_scheme: Optional[ColorScheme] = None,
        selection_mode: TableSelectionMode = TableSelectionMode.SINGLE,
        column_presentation: ColumnPresentationState | None = None,
        parent=None
    ):
        super().__init__(parent)

        self.color_scheme = color_scheme or ColorScheme()
        self.style_gen = StyleSheetGenerator(self.color_scheme)
        self._selection_mode = selection_mode
        self.column_presentation = column_presentation or ColumnPresentationState(
            parent=self
        )
        self._applying_column_presentation = False
        self.column_presentation.changed.connect(self._apply_column_presentation)

        # Data storage
        self.all_items: Dict[str, T] = {}
        self._base_filtered_items: Dict[str, T] = {}
        self.filtered_items: Dict[str, T] = {}

        # Will be set by subclass or set_items()
        self._search_service: Optional[SearchService[T]] = None
        self._populate_token = 0

        # Create UI components
        self._setup_ui()
        self._setup_connections()

    def _setup_ui(self):
        """Set up the base UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # Search input
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.get_search_placeholder())
        layout.addWidget(self.search_input)
        
        # Status label
        self.status_label = QLabel("No items loaded")
        layout.addWidget(self.status_label)
        
        # Table and its column-derived controls
        self.table_widget = QTableWidget()
        self._configure_table()
        from pyqt_reactive.widgets.shared.column_filter_widget import (
            MultiColumnFilterPanel,
        )

        self.column_filter_panel = MultiColumnFilterPanel(
            color_scheme=self.color_scheme,
            column_presentation=self.column_presentation,
            parent=self,
        )
        self._column_filter_context_widget: QWidget | None = None
        self.column_filter_splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.column_filter_splitter.addWidget(self.column_filter_panel)

        self.content_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.content_splitter.addWidget(self.column_filter_splitter)
        self.content_splitter.addWidget(self.table_widget)
        self.content_splitter.setStretchFactor(0, 0)
        self.content_splitter.setStretchFactor(1, 1)
        layout.addWidget(self.content_splitter, 1)
        
        # Apply styling
        self.table_widget.setStyleSheet(self.style_gen.generate_table_widget_style())

    @property
    def column_filter_context_widget(self) -> QWidget | None:
        """Return the optional widget stacked above the column-filter panel."""

        return self._column_filter_context_widget

    def set_column_filter_context_widget(self, widget: QWidget | None) -> None:
        """Place a domain-owned context widget above the generic filter panel.

        The table browser retains ownership of filter construction and state;
        consumers can contribute spatial context without reparenting or
        reconstructing :attr:`column_filter_panel` themselves.
        """

        current = self._column_filter_context_widget
        if current is widget:
            return
        if current is not None:
            current.setParent(None)

        self._column_filter_context_widget = widget
        if widget is None:
            return

        self.column_filter_splitter.insertWidget(0, widget)
        self.column_filter_splitter.setStretchFactor(0, 1)
        self.column_filter_splitter.setStretchFactor(1, 1)

    def _configure_table(self):
        """Configure table based on column definitions."""
        columns = self.get_columns()
        self._apply_column_config(columns)

        # Configure selection mode
        self.table_widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_widget.setSelectionMode(self._selection_mode.qt_mode)
        self.table_widget.setSortingEnabled(True)

        # Configure text display for proper truncation with ellipsis
        self.table_widget.setWordWrap(False)
        self.table_widget.setTextElideMode(Qt.TextElideMode.ElideRight)

    def _apply_column_config(self, columns: List[ColumnDef]):
        """Apply columns during initial setup and dynamic reconfiguration."""
        self.column_presentation.set_columns(columns)
        self.table_widget.setColumnCount(len(columns))
        self.table_widget.setHorizontalHeaderLabels([col.name for col in columns])

        # Configure header
        header = self.table_widget.horizontalHeader()
        header.setSectionsMovable(True)

        for i, col in enumerate(columns):
            mode = (
                QHeaderView.ResizeMode.Interactive
                if col.resizable
                else QHeaderView.ResizeMode.Fixed
            )
            header.setSectionResizeMode(i, mode)
            if col.width:
                self.table_widget.setColumnWidth(i, col.width)

        self._apply_column_presentation()

    def _apply_column_presentation(self) -> None:
        """Project the shared column order and visibility onto the header."""
        if not hasattr(self, "table_widget"):
            return
        columns = self.column_presentation.columns
        if self.table_widget.columnCount() != len(columns):
            return

        header = self.table_widget.horizontalHeader()
        logical_by_key = {column.key: index for index, column in enumerate(columns)}
        self._applying_column_presentation = True
        try:
            for visual_index, key in enumerate(self.column_presentation.resolved_keys()):
                logical_index = logical_by_key[key]
                current_visual_index = header.visualIndex(logical_index)
                if current_visual_index != visual_index:
                    header.moveSection(current_visual_index, visual_index)

            preference = self.column_presentation.preference
            for logical_index, column in enumerate(columns):
                self.table_widget.setColumnHidden(
                    logical_index,
                    not preference.is_visible(column.key),
                )
        finally:
            self._applying_column_presentation = False

    def reconfigure_columns(self):
        """Reconfigure table columns. Call when get_columns() returns different values."""
        columns = self.get_columns()
        self._apply_column_config(columns)
        self._rebuild_column_filters()
        self._apply_column_filters()

    def _setup_connections(self):
        """Connect signals to slots."""
        self.search_input.textChanged.connect(self._on_search_changed)
        self.table_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self.table_widget.itemDoubleClicked.connect(self._on_double_click)
        self.table_widget.horizontalHeader().sectionMoved.connect(
            self._on_header_section_moved
        )
        self.column_filter_panel.filters_changed.connect(
            self._apply_column_filters
        )
        self.column_filter_panel.filter_selection_changed.connect(
            self.column_filter_selection_changed.emit
        )

    def _on_header_section_moved(
        self,
        _logical_index: int,
        _old_visual_index: int,
        _new_visual_index: int,
    ) -> None:
        """Publish direct header reordering through the shared preference."""
        if self._applying_column_presentation:
            return
        header = self.table_widget.horizontalHeader()
        columns = self.column_presentation.columns
        ordered_keys = tuple(
            columns[header.logicalIndex(visual_index)].key
            for visual_index in range(header.count())
        )
        self.column_presentation.set_preference(
            self.column_presentation.preference.with_resolved_order(
                ordered_keys,
                columns,
            )
        )

    def _on_search_changed(self, search_term: str):
        """Handle search input changes."""
        self.set_filtered_items(self.search_items(search_term))

    def search_items(self, search_term: str) -> Dict[str, T]:
        """Return items matching the table browser's configured search semantics."""
        if self._search_service is None:
            raise RuntimeError("Table search requires set_items() before filtering.")
        return self._search_service.filter(search_term)

    def _on_selection_changed(self):
        """Handle table selection changes."""
        selected_keys = self.get_selected_keys()
        if not selected_keys:
            return  # Valid: user clicked empty area

        if self._selection_mode is TableSelectionMode.MULTI:
            # Multi-select: emit list of keys
            self.items_selected.emit(selected_keys)
            self.on_items_selected(selected_keys)
        else:
            # Single-select: emit first key and item
            key = selected_keys[0]
            item = self.filtered_items[key]
            self.item_selected.emit(key, item)
            self.on_item_selected(key, item)

    def _on_double_click(self, table_item: QTableWidgetItem):
        """Handle double-click on table row."""
        row = table_item.row()
        key_item = self.table_widget.item(row, 0)
        key = key_item.data(Qt.ItemDataRole.UserRole)

        # Key in table → item in filtered_items (invariant)
        item = self.filtered_items[key]
        self.item_double_clicked.emit(key, item)
        self.on_item_double_clicked(key, item)

    def get_selected_keys(self) -> List[str]:
        """Return list of selected item keys. Works for both single and multi-select."""
        selected_rows = set()
        for table_item in self.table_widget.selectedItems():
            selected_rows.add(table_item.row())

        keys = []
        for row in sorted(selected_rows):
            key_item = self.table_widget.item(row, 0)
            keys.append(key_item.data(Qt.ItemDataRole.UserRole))
        return keys

    def select_key(self, key: str) -> bool:
        """Select one row by semantic item key."""
        return bool(self.select_keys([key]))

    def select_keys(self, keys: List[str]) -> List[str]:
        """Select rows by semantic item keys and return the keys found."""
        key_set = set(keys)
        found: List[str] = []
        selection_model = self.table_widget.selectionModel()
        self.table_widget.clearSelection()

        for row in range(self.table_widget.rowCount()):
            key_item = self.table_widget.item(row, 0)
            if key_item is None:
                continue
            row_key = key_item.data(Qt.ItemDataRole.UserRole)
            if row_key not in key_set:
                continue

            found.append(row_key)
            index = self.table_widget.model().index(row, 0)
            selection_model.select(
                index,
                QItemSelectionModel.SelectionFlag.Select
                | QItemSelectionModel.SelectionFlag.Rows,
            )

        if found:
            first_row = _first_row_for_key(self.table_widget, found[0])
            if first_row is not None:
                self.table_widget.scrollToItem(self.table_widget.item(first_row, 0))

        return found

    def _update_status(self):
        """Update status label with current counts."""
        total = len(self.all_items)
        filtered = len(self.filtered_items)
        self.status_label.setText(f"Showing {filtered}/{total} items")

    def set_items(self, items: Dict[str, T]):
        """Set items to display in the table."""
        self.all_items = items
        self._base_filtered_items = items.copy()

        # Initialize search service only if all_items changed (not just filtered_items)
        if self._search_service is None:
            self._search_service = SearchService(
                all_items=self.all_items,
                searchable_text_extractor=self.get_searchable_text
            )
        else:
            self._search_service.update_items(self.all_items)

        self._rebuild_column_filters()
        self._apply_column_filters()

    def set_filtered_items(self, filtered_items: Dict[str, T]):
        """Set the external/base item projection and apply column filters.

        Use this for search, tree, folder, or other domain filters that compose
        with the generic filters declared by :class:`ColumnDef`.
        """
        self._base_filtered_items = filtered_items.copy()
        self._apply_column_filters()

    def set_column_filter_selection(
        self,
        column_key: str,
        selected_values: Sequence[str] | None,
    ) -> bool:
        """Set one generic column filter without exposing its widget."""
        return self.column_filter_panel.set_filter_selection(
            column_key,
            selected_values,
        )

    def column_filter_selection(
        self,
        column_key: str,
    ) -> frozenset[str] | None:
        """Return one generic column filter selection by semantic key."""
        return self.column_filter_panel.filter_selection(column_key)

    def is_column_filter_active(self, column_key: str) -> bool:
        """Return whether one generic column filter excludes values."""
        return self.column_filter_panel.is_filter_active(column_key)

    def _rebuild_column_filters(self) -> None:
        """Build filter choices from declared columns and authoritative items."""
        from pyqt_reactive.widgets.shared.column_filter_widget import ColumnFilterDef

        columns = self.column_presentation.columns
        filter_definitions = []
        for column_index, column in enumerate(columns):
            if not column.filterable:
                continue
            unique_values = {
                value
                for item in self.all_items.values()
                for value in self._column_filter_values(
                    column,
                    column_index,
                    item,
                )
            }
            filter_definitions.append(
                ColumnFilterDef(column, tuple(sorted(unique_values)))
            )
        self.column_filter_panel.set_column_filters(filter_definitions)

    def _column_filter_values(
        self,
        column: ColumnDef,
        column_index: int,
        item: T,
    ) -> tuple[str, ...]:
        """Return normalized values for one declared column and row."""
        if column.filter_values is not None:
            return tuple(
                str(value)
                for value in column.filter_values(item)
                if value is not None
            )
        row_data = self.extract_row_data(item)
        if column_index >= len(row_data):
            raise ValueError(
                f"Column {column.key!r} has no value at row index {column_index}"
            )
        return (str(row_data[column_index]),)

    def _apply_column_filters(self) -> None:
        """Compose active declared-column filters with the external projection."""
        active_filters = self.column_filter_panel.get_active_filters()
        columns = self.column_presentation.columns
        column_indexes = {
            column.key: index for index, column in enumerate(columns)
        }
        columns_by_key = {column.key: column for column in columns}

        if active_filters:
            filtered_items = {
                key: item
                for key, item in self._base_filtered_items.items()
                if all(
                    bool(
                        set(
                            self._column_filter_values(
                                columns_by_key[column_key],
                                column_indexes[column_key],
                                item,
                            )
                        )
                        & selected_values
                    )
                    for column_key, selected_values in active_filters.items()
                )
            }
        else:
            filtered_items = self._base_filtered_items.copy()

        self._set_displayed_items(filtered_items)

    def _set_displayed_items(self, filtered_items: Dict[str, T]) -> None:
        """Publish and render the final composed item projection."""
        self.filtered_items = filtered_items
        self._populate_token += 1
        if len(self.filtered_items) > self.INCREMENTAL_POPULATE_THRESHOLD:
            self.populate_table_incremental(
                self.filtered_items,
                token=self._populate_token,
                batch_size=self.INCREMENTAL_BATCH_SIZE,
            )
        else:
            self.populate_table(self.filtered_items)
        self._update_status()

    def populate_table(self, items: Dict[str, T]):
        """Populate the table with the given items."""
        sorting_enabled = self.table_widget.isSortingEnabled()
        self.table_widget.setSortingEnabled(False)
        self.table_widget.setUpdatesEnabled(False)
        self.table_widget.blockSignals(True)
        try:
            self.table_widget.setRowCount(len(items))

            for row, (key, item) in enumerate(items.items()):
                row_data = self.extract_row_data(item)

                for col, value in enumerate(row_data):
                    table_item = QTableWidgetItem(str(value))

                    # Store key in first column for lookup
                    if col == 0:
                        table_item.setData(Qt.ItemDataRole.UserRole, key)

                    # Enable proper text truncation with ellipsis
                    table_item.setTextAlignment(
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                    )
                    table_item.setFlags(
                        table_item.flags() & ~Qt.ItemFlag.ItemIsEditable
                    )

                    self.table_widget.setItem(row, col, table_item)
        finally:
            self.table_widget.blockSignals(False)
            self.table_widget.setUpdatesEnabled(True)
            self.table_widget.setSortingEnabled(sorting_enabled)

    def populate_table_incremental(
        self,
        items: Dict[str, T],
        *,
        token: int,
        batch_size: int = 200,
    ) -> None:
        """Populate table in batches to avoid blocking the UI."""
        sorting_enabled = self.table_widget.isSortingEnabled()
        self.table_widget.setSortingEnabled(False)
        self.table_widget.blockSignals(True)

        items_list = list(items.items())
        self.table_widget.setRowCount(len(items_list))

        def fill_batch(start_index: int) -> None:
            if token != self._populate_token:
                return

            end_index = min(start_index + batch_size, len(items_list))
            self.table_widget.setUpdatesEnabled(False)
            try:
                for row in range(start_index, end_index):
                    key, item = items_list[row]
                    row_data = self.extract_row_data(item)

                    for col, value in enumerate(row_data):
                        table_item = QTableWidgetItem(str(value))

                        if col == 0:
                            table_item.setData(Qt.ItemDataRole.UserRole, key)

                        table_item.setTextAlignment(
                            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                        )
                        table_item.setFlags(
                            table_item.flags() & ~Qt.ItemFlag.ItemIsEditable
                        )

                        self.table_widget.setItem(row, col, table_item)
            finally:
                self.table_widget.setUpdatesEnabled(True)

            if end_index < len(items_list):
                QTimer.singleShot(0, lambda: fill_batch(end_index))
            else:
                self.table_widget.blockSignals(False)
                self.table_widget.setSortingEnabled(sorting_enabled)

        QTimer.singleShot(0, lambda: fill_batch(0))

    def refresh(self):
        """Refresh the table display."""
        self.populate_table(self.filtered_items)
        self._update_status()

    # =========================================================================
    # Abstract methods - subclasses must implement
    # =========================================================================

    @abstractmethod
    def get_columns(self) -> List[ColumnDef]:
        """Return column definitions for the table."""
        raise NotImplementedError

    @abstractmethod
    def extract_row_data(self, item: T) -> List[str]:
        """Extract display values for a table row from an item."""
        raise NotImplementedError

    @abstractmethod
    def get_searchable_text(self, item: T) -> str:
        """Return searchable text for an item."""
        raise NotImplementedError

    # =========================================================================
    # Optional hooks - subclasses can override
    # =========================================================================

    def get_search_placeholder(self) -> str:
        """Return placeholder text for search input."""
        return "Search..."

    def on_item_selected(self, key: str, item: T):
        """Called when an item is selected (single-select mode). Override to handle."""
        pass

    def on_items_selected(self, keys: List[str]):
        """Called when items are selected (multi-select mode). Override to handle."""
        pass

    def on_item_double_clicked(self, key: str, item: T):
        """Called when an item is double-clicked. Override to handle action."""
        pass


def _first_row_for_key(table_widget: QTableWidget, key: str) -> int | None:
    for row in range(table_widget.rowCount()):
        key_item = table_widget.item(row, 0)
        if key_item is not None and key_item.data(Qt.ItemDataRole.UserRole) == key:
            return row
    return None
