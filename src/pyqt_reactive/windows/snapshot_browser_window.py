"""
Snapshot Browser Window - Time-travel visualization using AbstractTableBrowser.

Displays all history snapshots in a table view with search/filter support.
Double-click to time-travel to any snapshot.
"""

from dataclasses import dataclass

from objectstate.object_state import ObjectStateRegistry
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QLabel,
    QMainWindow,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.shared.abstract_table_browser import (
    AbstractTableBrowser,
    ColumnDef,
    TableSelectionMode,
)
from pyqt_reactive.widgets.time_travel import TimeTravelCommands, TimeTravelWidget


@dataclass
class SnapshotInfo:
    """Snapshot data for display in table."""

    index: int
    timestamp: str
    timestamp_raw: float
    label: str
    num_states: int
    is_current: bool


class SnapshotTableBrowser(AbstractTableBrowser[SnapshotInfo]):
    """Table browser for time-travel snapshots."""

    def __init__(
        self,
        *args,
        commands: TimeTravelCommands,
        **kwargs,
    ) -> None:
        self._commands = commands
        super().__init__(*args, **kwargs)

    def get_columns(self) -> list[ColumnDef]:
        return [
            ColumnDef("Index", "index", width=60),
            ColumnDef("Time", "timestamp", width=100),
            ColumnDef("Label", "label", width=250),
            ColumnDef("States", "num_states", width=60),
        ]

    def extract_row_data(self, item: SnapshotInfo) -> list[str]:
        prefix = "→ " if item.is_current else ""
        return [
            f"{prefix}{item.index}",
            item.timestamp,
            item.label,
            str(item.num_states),
        ]

    def get_searchable_text(self, item: SnapshotInfo) -> str:
        return f"{item.label} {item.timestamp}"

    def get_search_placeholder(self) -> str:
        return "Search snapshots..."

    def on_item_double_clicked(self, key: str, item: SnapshotInfo):
        """Time-travel to the selected snapshot by index."""
        if not self._commands.to_index(item.index):
            return
        self._refresh_from_registry()

    def _refresh_from_registry(self):
        """Refresh table from ObjectStateRegistry history."""
        history = self._commands.history()
        items: dict[str, SnapshotInfo] = {}

        for h in history:
            key = str(h["index"])
            items[key] = SnapshotInfo(
                index=h["index"],
                timestamp=h["timestamp"],
                timestamp_raw=0.0,  # Not exposed by get_history_info
                label=h["label"],
                num_states=h["num_states"],
                is_current=h["is_current"],
            )

        self.set_items(items)


class SnapshotBrowserWindow(QMainWindow):
    """Main window for browsing time-travel snapshots."""

    def __init__(
        self,
        color_scheme: ColorScheme | None = None,
        *,
        commands: TimeTravelCommands,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Snapshot Browser - Time Travel")
        self.resize(700, 500)

        # Add Dialog hint so tiling WMs don't fullscreen this window
        # QMainWindow defaults to Window type which tiling WMs tile/fullscreen
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Dialog)

        self.color_scheme = color_scheme or ColorScheme()
        self.commands = commands

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        self._setup_toolbar()

        # Snapshot table browser (main content)
        self.browser = SnapshotTableBrowser(
            color_scheme=self.color_scheme,
            selection_mode=TableSelectionMode.SINGLE,
            commands=self.commands,
            parent=self,
        )
        layout.addWidget(self.browser, 1)  # stretch factor 1

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        # Timeline widget at bottom (stays in sync with all other timeline widgets)
        # No browse button - we're already in the browser window
        self.timeline_widget = TimeTravelWidget(
            color_scheme=self.color_scheme,
            show_browse_button=False,
            commands=self.commands,
            parent=self,
        )
        layout.addWidget(self.timeline_widget)

        # Connect timeline widget position changes to refresh table
        self.timeline_widget.position_changed.connect(self._on_timeline_position_changed)

        # Subscribe to history changes to refresh table (event-based, no polling)
        self._history_subscription = ObjectStateRegistry.add_history_changed_callback(
            self._on_refresh
        )
        self.destroyed.connect(self._history_subscription.release)

        # Initial load
        self.browser._refresh_from_registry()

    def _setup_toolbar(self):
        """Create toolbar with actions."""
        toolbar = QToolBar("Snapshot Actions")
        self.addToolBar(toolbar)

        # Jump to HEAD action
        head_action = QAction("⏭ HEAD", self)
        head_action.setToolTip("Return to present (latest state)")
        head_action.triggered.connect(self._on_jump_to_head)
        toolbar.addAction(head_action)

        # Refresh action
        refresh_action = QAction("🔄 Refresh", self)
        refresh_action.setToolTip("Refresh snapshot list")
        refresh_action.triggered.connect(self._on_refresh)
        toolbar.addAction(refresh_action)

        # Separator before branch section
        toolbar.addSeparator()

        # Branch dropdown
        toolbar.addWidget(QLabel("Branch:"))
        self.branch_combo = QComboBox()
        self.branch_combo.setToolTip("Switch branch")
        self.branch_combo.setStyleSheet(self.color_scheme.styles.generate_combobox_style())
        self.branch_combo.currentTextChanged.connect(self._on_branch_changed)
        toolbar.addWidget(self.branch_combo)

        # Delete branch action
        self.delete_branch_action = QAction("🗑️", self)
        self.delete_branch_action.setToolTip("Delete current branch (cannot delete 'main')")
        self.delete_branch_action.triggered.connect(self._on_delete_branch)
        toolbar.addAction(self.delete_branch_action)

        # Initial branch UI state
        self._update_branch_ui()

    def _update_branch_ui(self):
        """Update branch dropdown and delete button state."""
        branches = ObjectStateRegistry.list_branches()
        self.branch_combo.blockSignals(True)
        self.branch_combo.clear()
        for b in branches:
            self.branch_combo.addItem(b["name"])
            if b["is_current"]:
                self.branch_combo.setCurrentText(b["name"])
        self.branch_combo.blockSignals(False)

        # Can't delete main
        current = ObjectStateRegistry.get_current_branch()
        self.delete_branch_action.setEnabled(current != "main")

    def _on_branch_changed(self, name: str):
        """Handle branch dropdown selection change."""
        if name and name != ObjectStateRegistry.get_current_branch():
            if not self.commands.switch_branch(name):
                self._update_branch_ui()
                return
        self._update_branch_ui()

    def _on_delete_branch(self):
        """Delete current branch and switch to main."""
        current = ObjectStateRegistry.get_current_branch()
        if current != "main":
            if not self.commands.delete_branch(current):
                return

    def _on_jump_to_head(self):
        """Return to present state."""
        if not self.commands.to_head():
            return
        self.browser._refresh_from_registry()

    def _on_refresh(self):
        """Refresh the snapshot list and branch UI."""
        self.browser._refresh_from_registry()
        self._update_branch_ui()

    def _on_timeline_position_changed(self, index: int):
        """Handle timeline widget position change - refresh table."""
        self.browser._refresh_from_registry()

    def closeEvent(self, event):  # noqa: N802 - Qt virtual method name
        """Unsubscribe from callbacks on close."""
        self._history_subscription.release()
        super().closeEvent(event)
