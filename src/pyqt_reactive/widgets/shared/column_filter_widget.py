"""
Column filter widget with checkboxes for unique values.

Provides Excel-like column filtering with checkboxes for each unique value.
Multiple columns can be filtered simultaneously with AND logic across columns.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from pyqt_reactive.forms.layout_constants import COMPACT_LAYOUT
from pyqt_reactive.theming import ColorScheme, StyleSheetGenerator
from pyqt_reactive.widgets.shared.abstract_table_browser import (
    ColumnDef,
    ColumnPresentation,
    ColumnPresentationState,
)
from pyqt_reactive.widgets.shared.reflowing_vertical_scroll_area import (
    ReflowingVerticalScrollArea,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ColumnFilterDef:
    """Filter values owned by one declared semantic column."""

    column: ColumnDef
    unique_values: tuple[str, ...]


class ColumnPresentationDialog(QDialog):
    """Keyboard-accessible visibility/order editor for declared columns."""

    def __init__(
        self,
        column_presentation: ColumnPresentationState,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.column_presentation = column_presentation
        self.setWindowTitle("Configure Columns")

        layout = QVBoxLayout(self)
        self.column_list = QListWidget(self)
        self.column_list.setAccessibleName("Table columns")
        self.column_list.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove
        )
        layout.addWidget(self.column_list)

        move_layout = QHBoxLayout()
        self.move_up_button = QPushButton("Move Up", self)
        self.move_up_button.setAccessibleName("Move selected column up")
        self.move_up_button.clicked.connect(lambda: self._move_current(-1))
        move_layout.addWidget(self.move_up_button)
        self.move_down_button = QPushButton("Move Down", self)
        self.move_down_button.setAccessibleName("Move selected column down")
        self.move_down_button.clicked.connect(lambda: self._move_current(1))
        move_layout.addWidget(self.move_down_button)
        self.reset_button = QPushButton("Reset", self)
        self.reset_button.setAccessibleName(
            "Reset column visibility and declaration order"
        )
        self.reset_button.clicked.connect(self.reset_to_declaration)
        move_layout.addWidget(self.reset_button)
        layout.addLayout(move_layout)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._populate(self.column_presentation.resolved_columns())

    def _populate(
        self,
        columns: Sequence[ColumnDef],
        *,
        show_all: bool = False,
    ) -> None:
        self.column_list.clear()
        preference = self.column_presentation.preference
        for column in columns:
            item = QListWidgetItem(column.name, self.column_list)
            item.setData(Qt.ItemDataRole.UserRole, column.key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if show_all or preference.is_visible(column.key)
                else Qt.CheckState.Unchecked
            )
        if self.column_list.count():
            self.column_list.setCurrentRow(0)

    def _move_current(self, offset: int) -> None:
        current_row = self.column_list.currentRow()
        target_row = current_row + offset
        if current_row < 0 or not 0 <= target_row < self.column_list.count():
            return
        item = self.column_list.takeItem(current_row)
        self.column_list.insertItem(target_row, item)
        self.column_list.setCurrentRow(target_row)

    def reset_to_declaration(self) -> None:
        """Restore declared order and make every declared column visible."""
        self._populate(self.column_presentation.columns, show_all=True)

    def preference(self) -> ColumnPresentation:
        """Build an immutable preference from the editor contents."""
        current_order: list[str] = []
        current_hidden_keys: set[str] = set()
        for row in range(self.column_list.count()):
            item = self.column_list.item(row)
            key = item.data(Qt.ItemDataRole.UserRole)
            current_order.append(key)
            if item.checkState() != Qt.CheckState.Checked:
                current_hidden_keys.add(key)

        current_keys = set(current_order)
        reordered = self.column_presentation.preference.with_resolved_order(
            current_order,
            self.column_presentation.columns,
        )

        stale_hidden_keys = (
            self.column_presentation.preference.hidden_keys - current_keys
        )
        return ColumnPresentation(
            reordered.ordered_keys,
            frozenset(stale_hidden_keys | current_hidden_keys),
        )


class ColumnPresentationControl(QPushButton):
    """Open the generic column presentation editor."""

    def __init__(
        self,
        column_presentation: ColumnPresentationState,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Columns…", parent)
        self.column_presentation = column_presentation
        self.setAccessibleName("Configure table columns")
        self.clicked.connect(self.open_editor)
        self.column_presentation.changed.connect(self._sync_enabled)
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        self.setEnabled(bool(self.column_presentation.columns))

    def create_editor(self) -> ColumnPresentationDialog:
        """Create an editor for the current declared columns."""
        return ColumnPresentationDialog(self.column_presentation, self)

    def open_editor(self) -> None:
        """Apply accepted presentation choices to the shared state."""
        editor = self.create_editor()
        try:
            if editor.exec() == QDialog.DialogCode.Accepted:
                self.column_presentation.set_preference(editor.preference())
        finally:
            editor.deleteLater()


class NonCompressingSplitter(QSplitter):
    """
    A QSplitter that maintains its size based on widget sizes, not available space.

    When handles are moved, this splitter grows the total size instead of
    redistributing space among widgets.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Remove maximum height constraint
        self.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX
        # Flag to prevent resize event from interfering
        self._in_move = False

    def moveSplitter(self, pos, index):
        """Override to grow total size instead of redistributing space."""
        # Get current sizes before any changes
        old_sizes = self.sizes()
        if not old_sizes or index <= 0 or index > len(old_sizes):
            super().moveSplitter(pos, index)
            return

        # Set flag to prevent resize interference
        self._in_move = True

        # Calculate the position change
        # The handle is between widget[index-1] and widget[index]
        old_pos = sum(old_sizes[:index]) + (index * self.handleWidth())
        delta = pos - old_pos

        # Create new sizes - only change the widget above the handle
        new_sizes = old_sizes.copy()
        new_sizes[index - 1] = max(0, old_sizes[index - 1] + delta)

        # Don't shrink the widget below - keep all other widgets the same size
        # This means the total size will grow/shrink

        # Calculate new total height
        total_height = sum(new_sizes)
        num_handles = max(0, self.count() - 1)
        total_height += num_handles * self.handleWidth()

        # Set the new sizes FIRST before resizing
        # This prevents Qt from redistributing space when we resize
        self.setSizes(new_sizes)

        # Now update minimum height and resize
        self.setMinimumHeight(total_height)
        self.setFixedHeight(total_height)

        self._in_move = False

    def resizeEvent(self, event):
        """Override to prevent automatic size redistribution."""
        if self._in_move:
            # During moveSplitter, don't let Qt redistribute sizes
            super().resizeEvent(event)
            return

        # Normal resize - let Qt handle it
        super().resizeEvent(event)


class ColumnFilterWidget(QFrame):
    """
    Filter widget for a single column showing checkboxes for unique values.
    Uses compact styling matching parameter form manager.

    Signals:
        filter_changed: Emitted when filter selection changes
    """

    filter_changed = pyqtSignal()

    def __init__(
        self,
        column: ColumnDef,
        unique_values: Sequence[str],
        color_scheme: Optional[ColorScheme] = None,
        parent=None,
    ):
        """
        Initialize column filter widget.

        Args:
            column: Declared column identity and display projection
            unique_values: List of unique values in this column
            color_scheme: Color scheme for styling
            parent: Parent widget
        """
        super().__init__(parent)
        self.column = column
        self.column_key = column.key
        self.column_name = column.name
        self.unique_values = sorted(unique_values)  # Sort for consistent display
        self.checkboxes: Dict[str, QCheckBox] = {}
        self.color_scheme = color_scheme or ColorScheme()
        self.style_gen = StyleSheetGenerator(self.color_scheme)

        # Apply frame styling
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {self.color_scheme.to_hex(self.color_scheme.panel_bg)};
                border: 1px solid {self.color_scheme.to_hex(self.color_scheme.border_color)};
                border-radius: 3px;
            }}
        """)

        self._init_ui()
    
    def _init_ui(self):
        """Initialize the UI with compact styling matching parameter form manager."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*COMPACT_LAYOUT.main_layout_margins)
        layout.setSpacing(COMPACT_LAYOUT.main_layout_spacing)

        # Header: Column title on left, buttons on right (same row)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(COMPACT_LAYOUT.parameter_row_spacing)

        # Column title label (bold, accent color)
        title_label = QLabel(self.column_name)
        title_label.setStyleSheet(f"""
            QLabel {{
                font-weight: bold;
                color: {self.color_scheme.to_hex(self.color_scheme.text_accent)};
                font-size: 11px;
            }}
        """)
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        # All/None buttons (compact, matching parameter form buttons)
        select_all_btn = QPushButton("All")
        select_all_btn.setMaximumWidth(35)
        select_all_btn.setMaximumHeight(20)
        select_all_btn.setStyleSheet(self.style_gen.generate_button_style())
        select_all_btn.clicked.connect(self.select_all)
        header_layout.addWidget(select_all_btn)

        select_none_btn = QPushButton("None")
        select_none_btn.setMaximumWidth(35)
        select_none_btn.setMaximumHeight(20)
        select_none_btn.setStyleSheet(self.style_gen.generate_button_style())
        select_none_btn.clicked.connect(self.select_none)
        header_layout.addWidget(select_none_btn)

        layout.addLayout(header_layout)

        # Scrollable checkbox list - each filter has its own scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumHeight(60)  # Minimum to show a few items
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: {self.color_scheme.to_hex(self.color_scheme.window_bg)};
                border: none;
            }}
        """)

        checkbox_container = QWidget()
        checkbox_layout = QVBoxLayout(checkbox_container)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        checkbox_layout.setSpacing(COMPACT_LAYOUT.content_layout_spacing)

        # Create checkbox for each unique value (compact styling)
        for value in self.unique_values:
            checkbox = QCheckBox(str(value))
            checkbox.setChecked(True)  # Start with all selected
            checkbox.setStyleSheet(f"""
                QCheckBox {{
                    color: {self.color_scheme.to_hex(self.color_scheme.text_primary)};
                    spacing: 4px;
                    font-size: 11px;
                }}
                QCheckBox::indicator {{
                    width: 14px;
                    height: 14px;
                }}
            """)
            checkbox.stateChanged.connect(self._on_checkbox_changed)
            self.checkboxes[value] = checkbox
            checkbox_layout.addWidget(checkbox)

        checkbox_layout.addStretch()
        scroll_area.setWidget(checkbox_container)
        # Add scroll area with stretch factor so it takes up available space
        layout.addWidget(scroll_area, 1)

        # Count label (compact, secondary text color)
        self.count_label = QLabel()
        self.count_label.setStyleSheet(f"""
            QLabel {{
                font-size: 10px;
                color: {self.color_scheme.to_hex(self.color_scheme.text_disabled)};
            }}
        """)
        self._update_count_label()
        layout.addWidget(self.count_label)
    
    def _on_checkbox_changed(self):
        """Handle checkbox state change."""
        self._update_count_label()
        self.filter_changed.emit()
    
    def _update_count_label(self):
        """Update the count label showing selected/total."""
        selected_count = len(self.get_selected_values())
        total_count = len(self.unique_values)
        self.count_label.setText(f"{selected_count}/{total_count} selected")
    
    def select_all(self, block_signals: bool = False):
        """
        Select all checkboxes.

        Args:
            block_signals: If True, block signals while updating checkboxes
        """
        self._set_all_checkboxes(True, block_signals=block_signals)

    def select_none(self, block_signals: bool = False):
        """
        Deselect all checkboxes.

        Args:
            block_signals: If True, block signals while updating checkboxes
        """
        self._set_all_checkboxes(False, block_signals=block_signals)

    def _set_all_checkboxes(self, checked: bool, *, block_signals: bool = False) -> None:
        """Apply one checked state to all filter checkboxes."""
        for checkbox in self.checkboxes.values():
            if block_signals:
                checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            if block_signals:
                checkbox.blockSignals(False)

        if block_signals:
            self._update_count_label()
    
    def get_selected_values(self) -> Set[str]:
        """Get set of selected values."""
        return {value for value, checkbox in self.checkboxes.items() if checkbox.isChecked()}
    
    def set_selected_values(self, values: Set[str], block_signals: bool = False):
        """
        Set which values are selected.

        Args:
            values: Set of values to select
            block_signals: If True, block signals while updating checkboxes to prevent loops
        """
        for value, checkbox in self.checkboxes.items():
            if block_signals:
                checkbox.blockSignals(True)
            checkbox.setChecked(value in values)
            if block_signals:
                checkbox.blockSignals(False)

        # Update count label manually if signals were blocked
        if block_signals:
            self._update_count_label()


class MultiColumnFilterPanel(QWidget):
    """
    Panel containing filters for multiple columns with resizable splitters.

    Provides column-based filtering with AND logic across columns.
    Each filter can be resized independently using vertical splitters.

    Signals:
        filters_changed: Emitted when any filter changes
    """

    filters_changed = pyqtSignal()
    filter_selection_changed = pyqtSignal(str, object)

    def __init__(
        self,
        color_scheme: Optional[ColorScheme] = None,
        column_presentation: ColumnPresentationState | None = None,
        parent=None,
    ):
        """Initialize multi-column filter panel."""
        super().__init__(parent)
        self.column_filters: Dict[str, ColumnFilterWidget] = {}
        self._retained_selections: Dict[str, tuple[frozenset[str], bool]] = {}
        self.color_scheme = color_scheme or ColorScheme()
        self.style_gen = StyleSheetGenerator(self.color_scheme)
        self.column_presentation = column_presentation or ColumnPresentationState(
            parent=self
        )
        self.column_presentation.changed.connect(self._apply_column_presentation)
        self._init_ui()

    def _init_ui(self):
        """Initialize the UI with vertical splitter for resizable filters in a scroll area."""
        # Use custom non-compressing splitter so each filter can be resized
        self.splitter = NonCompressingSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)  # Prevent filters from collapsing
        self.splitter.setHandleWidth(5)  # Make handle more visible and easier to grab

        # Wrap splitter in scroll area so the whole group can scroll
        self.scroll_area = ReflowingVerticalScrollArea()
        self.scroll_area.setWidget(self.splitter)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        settings_layout = QHBoxLayout()
        settings_layout.setContentsMargins(0, 0, 0, 0)
        self.presentation_control = ColumnPresentationControl(
            self.column_presentation,
            self,
        )
        self.presentation_control.setStyleSheet(
            self.style_gen.generate_button_style()
        )
        settings_layout.addWidget(self.presentation_control)
        self.hidden_active_label = QLabel(self)
        self.hidden_active_label.setAccessibleName("Hidden active column filters")
        self.hidden_active_label.setStyleSheet(
            f"color: {self.color_scheme.to_hex(self.color_scheme.text_disabled)};"
        )
        self.hidden_active_label.setVisible(False)
        settings_layout.addWidget(self.hidden_active_label)
        settings_layout.addStretch()
        main_layout.addLayout(settings_layout)
        main_layout.addWidget(self.scroll_area)
        self._sync_filter_body_visibility()

    def showEvent(self, event):
        """Handle show event to recalculate initial splitter heights."""
        super().showEvent(event)
        if self.column_filters:
            self._update_splitter_sizes()
    
    def add_column_filter(
        self,
        column: ColumnDef,
        unique_values: Sequence[str],
    ) -> None:
        """
        Add a filter for a column.

        Args:
            column: Declared column identity and display projection
            unique_values: List of unique values in this column
        """
        declared_keys = {item.key for item in self.column_presentation.columns}
        if column.key not in declared_keys:
            raise ValueError(
                f"Filter column {column.key!r} is not declared by the table owner"
            )
        if column.key in self.column_filters:
            # Remove existing filter
            self.remove_column_filter(column.key)

        self._install_column_filter(column, unique_values)
        self._apply_column_presentation()

    def _install_column_filter(
        self,
        column: ColumnDef,
        unique_values: Sequence[str],
    ) -> None:
        # Create filter widget with color scheme
        filter_widget = ColumnFilterWidget(column, unique_values, self.color_scheme)
        filter_widget.filter_changed.connect(
            lambda column_key=column.key: self._on_filter_changed(column_key)
        )

        retained = self._retained_selections.get(column.key)
        if retained is not None:
            selected_values, was_all_selected = retained
            if not was_all_selected:
                filter_widget.set_selected_values(
                    set(selected_values) & set(filter_widget.unique_values),
                    block_signals=True,
                )

        # Add to splitter (each filter is independently resizable)
        self.splitter.addWidget(filter_widget)

        self.column_filters[column.key] = filter_widget
        self._sync_filter_body_visibility()

    def set_column_filters(self, filters: Sequence[ColumnFilterDef]) -> None:
        """Replace filter declarations while retaining keyed selections."""
        filter_keys = tuple(filter_def.column.key for filter_def in filters)
        if len(filter_keys) != len(set(filter_keys)):
            raise ValueError("Column filter keys must be unique")
        declared_keys = {item.key for item in self.column_presentation.columns}
        undeclared_keys = set(filter_keys) - declared_keys
        if undeclared_keys:
            raise ValueError(
                "Filter columns are not declared by the table owner: "
                f"{sorted(undeclared_keys)!r}"
            )

        self._remember_current_selections()
        for widget in self.column_filters.values():
            widget.setParent(None)
            widget.deleteLater()
        self.column_filters.clear()

        for filter_def in filters:
            self._install_column_filter(
                filter_def.column,
                filter_def.unique_values,
            )
        self._apply_column_presentation()
        self._sync_filter_body_visibility()

    def _sync_filter_body_visibility(self) -> None:
        """Collapse only the empty filter list, retaining column settings."""
        self.scroll_area.setVisible(bool(self.column_filters))

    def _remember_current_selections(self) -> None:
        for key, filter_widget in self.column_filters.items():
            selected = frozenset(filter_widget.get_selected_values())
            self._retained_selections[key] = (
                selected,
                len(selected) == len(filter_widget.unique_values),
            )

    def _apply_column_presentation(self) -> None:
        """Project shared declaration order/visibility onto filter panels."""
        preference = self.column_presentation.preference
        ordered_keys = tuple(
            key
            for key in self.column_presentation.resolved_keys()
            if key in self.column_filters
        )
        for index, key in enumerate(ordered_keys):
            widget = self.column_filters[key]
            self.splitter.insertWidget(index, widget)
            widget.setVisible(preference.is_visible(key))
        stale_keys = tuple(
            key for key in self.column_filters if key not in ordered_keys
        )
        for key in stale_keys:
            self.column_filters[key].setVisible(False)
        self.column_filters = {
            key: self.column_filters[key]
            for key in ordered_keys + stale_keys
        }
        self._update_hidden_active_label()
        self._update_splitter_sizes()
    
    def _update_splitter_sizes(self):
        """Update splitter sizes based on each filter's content."""
        visible_filters = [
            filter_widget
            for filter_widget in self.column_filters.values()
            if not filter_widget.isHidden()
        ]
        num_filters = len(visible_filters)
        if num_filters > 0:
            # Force layout update first to get accurate size hints
            for filter_widget in visible_filters:
                filter_widget.updateGeometry()

            # Size each filter based on its actual content (sizeHint)
            sizes = []
            for filter_widget in self.column_filters.values():
                # Get the widget's preferred size
                hint = filter_widget.sizeHint()
                # Use the height hint, with a minimum of 100px
                sizes.append(
                    max(100, hint.height()) if not filter_widget.isHidden() else 0
                )

            self.splitter.setSizes(sizes)

            # Set initial minimum height
            total_height = sum(sizes)
            num_handles = max(0, num_filters - 1)
            total_height += num_handles * self.splitter.handleWidth()
            self.splitter.setMinimumHeight(total_height)

            # Resize to the calculated height
            self.splitter.setFixedHeight(total_height)

            # Schedule a deferred update to fix layout after widgets are fully rendered
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, self._deferred_size_update)
        else:
            self.splitter.setMinimumHeight(0)
            self.splitter.setFixedHeight(0)

    def _deferred_size_update(self):
        """Deferred size update after widgets are fully rendered."""
        visible_filters = [
            filter_widget
            for filter_widget in self.column_filters.values()
            if not filter_widget.isHidden()
        ]
        num_filters = len(visible_filters)
        if num_filters > 0:
            # Force synchronous event processing to ensure layout is complete
            from PyQt6.QtWidgets import QApplication
            QApplication.processEvents()

            # Force a full layout pass first
            self.splitter.updateGeometry()
            for filter_widget in self.column_filters.values():
                filter_widget.layout().activate()
                filter_widget.updateGeometry()

            # Process events again after geometry updates
            QApplication.processEvents()

            # Recalculate sizes now that widgets are rendered
            sizes = []
            for filter_widget in self.column_filters.values():
                hint = filter_widget.sizeHint()
                sizes.append(
                    max(100, hint.height()) if not filter_widget.isHidden() else 0
                )

            self.splitter.setSizes(sizes)

            total_height = sum(sizes)
            num_handles = max(0, num_filters - 1)
            total_height += num_handles * self.splitter.handleWidth()
            self.splitter.setMinimumHeight(total_height)
            self.splitter.setFixedHeight(total_height)

            # Force a repaint to ensure proper rendering
            self.splitter.update()

    def remove_column_filter(self, column_key: str):
        """Remove a column filter."""
        if column_key in self.column_filters:
            widget = self.column_filters[column_key]
            selected = frozenset(widget.get_selected_values())
            self._retained_selections[column_key] = (
                selected,
                len(selected) == len(widget.unique_values),
            )
            # Remove from splitter
            widget.setParent(None)
            widget.deleteLater()
            del self.column_filters[column_key]
            # Update sizes after removing
            self._update_hidden_active_label()
            self._update_splitter_sizes()
            self._sync_filter_body_visibility()
    
    def clear_all_filters(self):
        """Remove all column filters."""
        for column_key in list(self.column_filters.keys()):
            self.remove_column_filter(column_key)
    
    def _on_filter_changed(self, column_key: str):
        """Handle filter change from any column."""
        self._remember_current_selections()
        self._update_hidden_active_label()
        self.filters_changed.emit()
        self.filter_selection_changed.emit(
            column_key,
            frozenset(self.column_filters[column_key].get_selected_values()),
        )

    def set_filter_selection(
        self,
        column_key: str,
        selected_values: Sequence[str] | None,
    ) -> bool:
        """Set one filter selection, or select all when values are ``None``."""
        filter_widget = self.column_filters.get(column_key)
        if filter_widget is None:
            return False
        values = (
            set(filter_widget.unique_values)
            if selected_values is None
            else set(selected_values)
        )
        filter_widget.set_selected_values(values, block_signals=True)
        self._on_filter_changed(column_key)
        return True

    def filter_selection(self, column_key: str) -> frozenset[str] | None:
        """Return one current selection, or ``None`` for an unknown key."""
        filter_widget = self.column_filters.get(column_key)
        if filter_widget is None:
            return None
        return frozenset(filter_widget.get_selected_values())

    def is_filter_active(self, column_key: str) -> bool:
        """Return whether one declared filter excludes any available value."""
        return column_key in self.get_active_filters()

    def _update_hidden_active_label(self) -> None:
        active_keys = set(self.get_active_filters())
        hidden_active_keys = [
            key
            for key in self.column_presentation.resolved_keys()
            if key in active_keys
            and not self.column_presentation.preference.is_visible(key)
        ]
        count = len(hidden_active_keys)
        self.hidden_active_label.setText(
            f"{count} hidden active filter{'s' if count != 1 else ''}"
        )
        columns_by_key = {
            column.key: column for column in self.column_presentation.columns
        }
        self.hidden_active_label.setToolTip(
            ", ".join(columns_by_key[key].name for key in hidden_active_keys)
        )
        self.hidden_active_label.setVisible(bool(hidden_active_keys))
    
    def get_active_filters(self) -> Dict[str, Set[str]]:
        """
        Get active filters for all columns.
        
        Returns:
            Dictionary mapping stable column key to selected values.
            Only includes columns where not all values are selected.
        """
        active_filters = {}
        declared_keys = {
            column.key for column in self.column_presentation.columns
        }
        for column_key, filter_widget in self.column_filters.items():
            if column_key not in declared_keys:
                continue
            selected = filter_widget.get_selected_values()
            # Only include if not all values are selected (i.e., actually filtering)
            if len(selected) < len(filter_widget.unique_values):
                active_filters[column_key] = selected
        return active_filters
    
    def apply_filters(self, data: List[Dict]) -> List[Dict]:
        """
        Apply filters to a list of data dictionaries.
        
        Args:
            data: List of dictionaries to filter
        Returns:
            Filtered list of dictionaries
        """
        active_filters = self.get_active_filters()
        
        if not active_filters:
            return data  # No filters active
        
        # Filter data with AND logic across columns
        filtered_data = []
        for item in data:
            matches = True
            for column_key, selected_values in active_filters.items():
                item_value = str(item.get(column_key, ''))
                if item_value not in selected_values:
                    matches = False
                    break
            if matches:
                filtered_data.append(item)
        
        return filtered_data
    
    def reset_all_filters(self):
        """Reset all filters to select all values."""
        for filter_widget in self.column_filters.values():
            filter_widget.select_all()
