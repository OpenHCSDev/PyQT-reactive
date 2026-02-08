"""Generic ZMQ server browser widget with domain hooks."""

from __future__ import annotations

import logging
from abc import ABC, ABCMeta, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from objectstate import spawn_thread_with_context

from pyqt_reactive.services import (
    BaseServerInfo,
    DefaultServerInfoParser,
    ServerInfoParserABC,
    ZMQServerScanService,
)
from pyqt_reactive.theming import StyleSheetGenerator
from pyqt_reactive.widgets.shared.button_panel import ButtonPanel
from pyqt_reactive.widgets.shared.manager_ui_scaffold import (
    create_manager_header,
    setup_vertical_manager_layout,
)
from pyqt_reactive.widgets.shared.tree_rebuild_coordinator import TreeRebuildCoordinator
from pyqt_reactive.widgets.shared.tree_state_adapter import TreeStateAdapter

logger = logging.getLogger(__name__)


class _CombinedMeta(ABCMeta, type(QWidget)):
    """Combined metaclass for ABC + PyQt6 QWidget."""


@dataclass(frozen=True)
class KillOperationPlan:
    """Server kill execution plan."""

    graceful: bool
    strict_failures: bool
    emit_signal_on_failure: bool
    success_message: str


class ZMQServerBrowserWidgetABC(QWidget, ABC, metaclass=_CombinedMeta):
    """Generic ZMQ browser UI infrastructure with domain extension hooks."""

    _TREE_INDENTATION_PX = 12

    server_killed = pyqtSignal(int)
    log_file_opened = pyqtSignal(str)
    _scan_complete = pyqtSignal(list)
    _kill_complete = pyqtSignal(bool, str)

    BUTTON_CONFIGS = [
        ("Refresh", "refresh", "Refresh server list"),
        ("Quit", "quit", "Gracefully quit selected servers"),
        ("Force Kill", "force_kill", "Force kill selected servers"),
    ]

    def __init__(
        self,
        *,
        ports_to_scan: List[int],
        title: str,
        style_generator: StyleSheetGenerator,
        scan_service: ZMQServerScanService,
        server_info_parser: ServerInfoParserABC | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.ports_to_scan = ports_to_scan
        self.title = title
        self.style_generator = style_generator
        self._scan_service = scan_service
        self._server_info_parser = (
            server_info_parser
            if server_info_parser is not None
            else DefaultServerInfoParser()
        )

        self.servers: List[Dict[str, Any]] = []
        self._last_known_servers: Dict[int, Dict[str, Any]] = {}
        self._is_cleaning_up = False
        self._tree_state_adapter = TreeStateAdapter()
        self._tree_rebuild_coordinator = TreeRebuildCoordinator(self._tree_state_adapter)

        self._button_actions: Dict[str, Callable[[], None]] = {
            "refresh": self.refresh_servers,
            "quit": self.quit_selected_servers,
            "force_kill": self.force_kill_selected_servers,
        }

        self._scan_complete.connect(self._update_server_list)
        self._kill_complete.connect(self._on_kill_complete)
        self.server_killed.connect(self._on_server_killed)

        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_servers)

        self._cleanup_timer = QTimer()
        self._cleanup_timer.timeout.connect(self._periodic_cleanup)
        self._cleanup_timer.start(1000)

        self.setup_ui()

    def __del__(self):
        self.cleanup()

    def cleanup(self) -> None:
        if self._is_cleaning_up:
            return
        self._is_cleaning_up = True

        if self.refresh_timer is not None:
            self.refresh_timer.stop()
            self.refresh_timer.deleteLater()
            self.refresh_timer = None
        if self._cleanup_timer is not None:
            self._cleanup_timer.stop()
            self._cleanup_timer.deleteLater()
            self._cleanup_timer = None

        self._on_browser_cleanup()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._is_cleaning_up:
            return
        self.refresh_servers()
        if self.refresh_timer is not None:
            self.refresh_timer.start(1000)
        self._on_browser_shown()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if self.refresh_timer is not None:
            self.refresh_timer.stop()
        self._on_browser_hidden()

    def setup_ui(self) -> None:
        header = self._create_header()

        self.server_tree = QTreeWidget()
        self.server_tree.setHeaderLabels(["Server / Worker", "Status", "Info"])
        self.server_tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.server_tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.server_tree.setColumnWidth(0, 250)
        self.server_tree.setColumnWidth(1, 100)
        self.server_tree.setIndentation(self._TREE_INDENTATION_PX)

        button_panel = self._create_button_panel()
        setup_vertical_manager_layout(
            owner=self,
            header=header,
            top_widget=self.server_tree,
            bottom_widget=button_panel,
        )

        self.server_tree.setStyleSheet(
            self.style_generator.generate_tree_widget_style()
            + """
            QTreeWidget::item {
                padding: 1px 0px 1px 0px;
            }
            QTreeView::branch {
                margin: 0px;
                padding: 0px;
            }
            """
        )

    def _create_header(self) -> QWidget:
        header_parts = create_manager_header(
            title=self.title,
            color_scheme=self.style_generator.color_scheme,
            enable_status_scrolling=False,
        )
        self.status_label = header_parts.status_label
        return header_parts.header

    def _create_button_panel(self) -> QWidget:
        panel = ButtonPanel(
            button_configs=self.BUTTON_CONFIGS,
            on_action=self._handle_button_action,
            style_generator=self.style_generator,
            grid_columns=0,
            parent=self,
        )
        self.refresh_btn = panel.get_button("refresh")
        self.quit_btn = panel.get_button("quit")
        self.force_kill_btn = panel.get_button("force_kill")
        return panel

    def _handle_button_action(self, action_id: str) -> None:
        action = self._button_actions[action_id]
        action()

    def refresh_servers(self) -> None:
        if self._is_cleaning_up:
            return

        def _scan_and_emit() -> None:
            servers = self._scan_service.scan_ports(self.ports_to_scan)
            self._scan_complete.emit(servers)

        spawn_thread_with_context(_scan_and_emit, name="scan_servers")

    def _ping_server(self, port: int) -> Optional[Dict[str, Any]]:
        return self._scan_service.ping_server(port)

    @pyqtSlot(list)
    def _update_server_list(self, servers: List[Dict[str, Any]]) -> None:
        self.servers = servers
        parsed_servers = [self._server_info_parser.parse(server) for server in servers]

        for server in servers:
            port = server.get("port")
            if port:
                self._last_known_servers[port] = server

        def _rebuild_contents() -> None:
            self._populate_tree(parsed_servers)

        self._tree_rebuild_coordinator.rebuild(self.server_tree, _rebuild_contents)

    @pyqtSlot(bool, str)
    def _on_kill_complete(self, success: bool, message: str) -> None:
        if not success:
            QMessageBox.warning(self, "Kill Failed", message)
        QTimer.singleShot(200, self.refresh_servers)

    @pyqtSlot(int)
    def _on_server_killed(self, port: int) -> None:
        if port in self._last_known_servers:
            del self._last_known_servers[port]

    def _periodic_cleanup(self) -> None:
        self._periodic_domain_cleanup()
        # Note: We intentionally do NOT clean up _last_known_servers here.
        # Servers are removed from the tree by _populate_tree based on scan misses.
        # Keeping _last_known_servers allows subclasses to access server info
        # (like active executions) even when ping temporarily fails.
        # Subclasses can implement their own cleanup via _periodic_domain_cleanup.

    def _collect_selected_server_ports(self, empty_selection_message: str) -> List[int]:
        selected_items = self.server_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", empty_selection_message)
            return []

        ports_to_kill: List[int] = []
        for item in selected_items:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, dict) and data.get("type") == "worker":
                continue
            if isinstance(data, dict) and "port" in data:
                ports_to_kill.append(data["port"])

        if not ports_to_kill:
            QMessageBox.warning(
                self, "No Servers", "No servers selected (only workers selected)."
            )
            return []
        return ports_to_kill

    def _confirm_kill_operation(
        self,
        *,
        title: str,
        message: str,
        default_button: QMessageBox.StandardButton,
    ) -> bool:
        reply = QMessageBox.question(
            self,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            default_button,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _spawn_server_kill_thread(
        self,
        *,
        ports: List[int],
        graceful: bool,
        strict_failures: bool,
        emit_signal_on_failure: bool,
        success_message: str,
    ) -> None:
        plan = KillOperationPlan(
            graceful=graceful,
            strict_failures=strict_failures,
            emit_signal_on_failure=emit_signal_on_failure,
            success_message=success_message,
        )

        def _kill_servers() -> None:
            success, message = self._kill_ports_with_plan(
                ports=ports,
                plan=plan,
                on_server_killed=lambda port: self.server_killed.emit(port),
            )
            self._kill_complete.emit(success, message)

        thread_name = "kill_servers" if graceful else "force_kill_servers"
        spawn_thread_with_context(_kill_servers, name=thread_name)

    def quit_selected_servers(self) -> None:
        ports_to_kill = self._collect_selected_server_ports(
            "Please select servers to quit."
        )
        if not ports_to_kill:
            return

        confirmed = self._confirm_kill_operation(
            title="Quit Confirmation",
            message=(
                f"Gracefully quit {len(ports_to_kill)} server(s)?\n\n"
                "For execution servers: kills workers only, server stays alive."
            ),
            default_button=QMessageBox.StandardButton.Yes,
        )
        if not confirmed:
            return

        self._spawn_server_kill_thread(
            ports=ports_to_kill,
            graceful=True,
            strict_failures=True,
            emit_signal_on_failure=False,
            success_message="All servers quit successfully",
        )

    def force_kill_selected_servers(self) -> None:
        ports_to_kill = self._collect_selected_server_ports(
            "Please select servers to force kill."
        )
        if not ports_to_kill:
            return

        confirmed = self._confirm_kill_operation(
            title="Force Kill Confirmation",
            message=(
                f"Force kill {len(ports_to_kill)} server(s)?\n\n"
                "For execution servers: kills workers AND server.\n"
                "For Napari viewers: kills the viewer process."
            ),
            default_button=QMessageBox.StandardButton.No,
        )
        if not confirmed:
            return

        self._spawn_server_kill_thread(
            ports=ports_to_kill,
            graceful=False,
            strict_failures=False,
            emit_signal_on_failure=True,
            success_message="Force kill operation completed (list will refresh)",
        )

    def _on_item_double_clicked(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "worker":
            data = data.get("server", {})

        log_file = data.get("log_file_path") if data else None
        if log_file and Path(log_file).exists():
            self.log_file_opened.emit(log_file)
            return
        QMessageBox.information(
            self,
            "No Log File",
            (
                "No log file available for this item.\n\n"
                f"Port: {data.get('port', 'unknown') if data else 'unknown'}"
            ),
        )

    @abstractmethod
    def _populate_tree(self, parsed_servers: List[BaseServerInfo]) -> None:
        """Build tree items from parsed server payloads."""

    @abstractmethod
    def _periodic_domain_cleanup(self) -> None:
        """Run domain-specific cleanup on timer ticks."""

    @abstractmethod
    def _kill_ports_with_plan(
        self,
        *,
        ports: List[int],
        plan: KillOperationPlan,
        on_server_killed: Callable[[int], None],
    ) -> tuple[bool, str]:
        """Execute blocking kill operation for selected ports."""

    @abstractmethod
    def _on_browser_shown(self) -> None:
        """Domain hook when widget becomes visible."""

    @abstractmethod
    def _on_browser_hidden(self) -> None:
        """Domain hook when widget is hidden."""

    @abstractmethod
    def _on_browser_cleanup(self) -> None:
        """Domain hook when widget is cleaned up."""
