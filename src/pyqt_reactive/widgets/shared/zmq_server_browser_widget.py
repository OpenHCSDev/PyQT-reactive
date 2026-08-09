"""Generic ZMQ server browser widget with domain hooks."""

from __future__ import annotations

import logging
import threading
from abc import ABC, ABCMeta, abstractmethod
from collections.abc import Callable
from enum import Enum
from pathlib import Path

from objectstate import spawn_thread_with_context
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)
from zmqruntime import EndpointShutdownMode
from zmqruntime.startup import EndpointStartupStatus

from pyqt_reactive.services.zmq_server_info import (
    BaseServerInfo,
)
from pyqt_reactive.services.zmq_server_scan_service import (
    EndpointObservationSnapshot,
    EndpointScanResult,
    StartingEndpointObservation,
    ZMQServerScanService,
)
from pyqt_reactive.theming import ColorScheme
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


class KillOperationKind(str, Enum):
    """Closed user-facing kill actions with member-owned execution policy."""

    def __new__(
        cls,
        value: str,
        shutdown_mode: EndpointShutdownMode,
        success_message: str,
        thread_name: str,
    ) -> KillOperationKind:
        member = str.__new__(cls, value)
        member._value_ = value
        member.shutdown_mode = shutdown_mode
        member.success_message = success_message
        member.thread_name = thread_name
        return member

    GRACEFUL = (
        "graceful",
        EndpointShutdownMode.GRACEFUL,
        "All servers quit successfully",
        "kill_servers",
    )
    FORCE = (
        "force",
        EndpointShutdownMode.FORCE,
        "All servers force killed successfully",
        "force_kill_servers",
    )

    @classmethod
    def from_force(cls, force: bool) -> KillOperationKind:
        """Resolve the caller's force flag at the declaration owner."""

        return cls.FORCE if force else cls.GRACEFUL


class BrowserLifecycleState:
    """Lifecycle guard for browser cleanup-sensitive operations."""

    def __init__(self) -> None:
        self._cleaning_up = False

    def is_cleaning_up(self) -> bool:
        return self._cleaning_up

    def begin_cleanup(self) -> bool:
        if self._cleaning_up:
            return False
        self._cleaning_up = True
        return True


class CoalescedScanRequests:
    """Single authority for one active scan and any newer invalidations."""

    def __init__(self) -> None:
        self._outstanding = 0
        self._lock = threading.Lock()

    def request(self) -> bool:
        """Record an invalidation and report whether its scan must start now."""

        with self._lock:
            self._outstanding += 1
            return self._outstanding == 1

    def complete(self) -> bool:
        """Complete the active scan and retain at most one follow-up request."""

        with self._lock:
            follow_up_required = self._outstanding > 1
            self._outstanding = 1 if follow_up_required else 0
            return follow_up_required

    def clear(self) -> None:
        """Discard all work when the browser lifecycle ends."""

        with self._lock:
            self._outstanding = 0

    def has_outstanding(self) -> bool:
        """Return whether a scan or a coalesced follow-up is outstanding."""

        with self._lock:
            return self._outstanding > 0


class ZMQServerBrowserWidgetABC(QWidget, ABC, metaclass=_CombinedMeta):
    """Generic ZMQ browser UI infrastructure with domain extension hooks."""

    _TREE_INDENTATION_PX = 12

    endpoint_terminated = pyqtSignal(int)
    endpoint_snapshot_changed = pyqtSignal(object)
    log_file_opened = pyqtSignal(str)
    _scan_complete = pyqtSignal(object)
    _kill_complete = pyqtSignal(bool, str)

    BUTTON_CONFIGS = [
        ("Refresh", "refresh", "Refresh server list"),
        ("Quit", "quit", "Gracefully quit selected servers"),
        ("Force Kill", "force_kill", "Force kill selected servers"),
    ]

    def __init__(
        self,
        *,
        ports_to_scan: list[int],
        title: str,
        color_scheme: ColorScheme,
        scan_service: ZMQServerScanService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.ports_to_scan = ports_to_scan
        self.title = title
        self.color_scheme = color_scheme
        self._scan_service = scan_service

        self._endpoint_snapshot = EndpointObservationSnapshot()
        self._scan_requests = CoalescedScanRequests()
        self._lifecycle_state = BrowserLifecycleState()
        self.destroyed.connect(
            lambda _object=None, lifecycle=self._lifecycle_state: lifecycle.begin_cleanup()
        )
        self._tree_state_adapter = TreeStateAdapter.default()
        self._tree_rebuild_coordinator = TreeRebuildCoordinator(self._tree_state_adapter)

        self._button_actions: dict[str, Callable[[], None]] = {
            "refresh": self.refresh_servers,
            "quit": self.quit_selected_servers,
            "force_kill": self.force_kill_selected_servers,
        }

        self._scan_complete.connect(self._update_server_list)
        self._kill_complete.connect(self._on_kill_complete)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_servers)

        self._cleanup_timer = QTimer(self)
        self._cleanup_timer.timeout.connect(self._periodic_cleanup)
        self._cleanup_timer.start(10000)

        self.setup_ui()

    def cleanup(self) -> None:
        if not self._lifecycle_state.begin_cleanup():
            return

        if self.refresh_timer is not None:
            self.refresh_timer.stop()
            self.refresh_timer.deleteLater()
            self.refresh_timer = None
        if self._cleanup_timer is not None:
            self._cleanup_timer.stop()
            self._cleanup_timer.deleteLater()
            self._cleanup_timer = None
        self._scan_requests.clear()

        self.on_browser_cleanup()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._lifecycle_state.is_cleaning_up():
            return
        self.refresh_servers()
        if self.refresh_timer is not None:
            self.refresh_timer.start(5000)
        self.on_browser_shown()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if self.refresh_timer is not None:
            self.refresh_timer.stop()
        self.on_browser_hidden()

    def setup_ui(self) -> None:
        header = self._create_header()

        self.server_tree = QTreeWidget()
        self.server_tree.setHeaderLabels(["Server / Worker", "Status", "Info"])
        self.server_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
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
            self.color_scheme.styles.generate_tree_widget_style()
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
            color_scheme=self.color_scheme,
            enable_status_scrolling=False,
        )
        self.manager_header = header_parts
        return header_parts.header

    def _create_button_panel(self) -> QWidget:
        panel = ButtonPanel(
            button_configs=self.BUTTON_CONFIGS,
            on_action=self._handle_button_action,
            color_scheme=self.color_scheme,
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
        if self._lifecycle_state.is_cleaning_up():
            return
        if not self._scan_requests.request():
            return
        self._start_server_scan()

    def _start_server_scan(self) -> None:
        """Run the active coalesced scan request."""

        previous_snapshot = self._endpoint_snapshot

        def _scan_and_emit() -> None:
            try:
                snapshot = self._scan_service.scan_ports(
                    self.ports_to_scan,
                    previous_snapshot=previous_snapshot,
                )
            except Exception:
                logger.exception("Failed to scan ZMQ server endpoints")
                snapshot = previous_snapshot
            if not self._lifecycle_state.is_cleaning_up():
                self._scan_complete.emit(
                    EndpointScanResult(
                        snapshot=snapshot,
                        base_snapshot=previous_snapshot,
                    )
                )

        spawn_thread_with_context(_scan_and_emit, name="scan_servers")

    @pyqtSlot(object)
    def _update_server_list(self, result: EndpointScanResult) -> None:
        """Commit one scan authority, then update every derived UI projection."""

        if not isinstance(result, EndpointScanResult):
            raise TypeError("ZMQ browser scan completion requires EndpointScanResult")
        if result.base_snapshot is self._endpoint_snapshot:
            self._commit_endpoint_snapshot(result.snapshot)
        else:
            self._scan_requests.request()
        if self._scan_requests.complete() and not self._lifecycle_state.is_cleaning_up():
            self._start_server_scan()

    def observe_endpoint_startup(
        self,
        port: int,
        status: EndpointStartupStatus,
    ) -> None:
        """Commit one endpoint lifecycle event into the shared snapshot authority."""

        if not isinstance(status, EndpointStartupStatus):
            raise TypeError("Endpoint startup observation requires EndpointStartupStatus")
        self._commit_endpoint_snapshot(self._endpoint_snapshot.with_startup_status(port, status))

    def _commit_endpoint_snapshot(
        self,
        snapshot: EndpointObservationSnapshot,
    ) -> None:
        """Install and publish the sole persistent endpoint observation state."""

        if snapshot == self._endpoint_snapshot:
            return
        self._endpoint_snapshot = snapshot
        self.render_endpoint_snapshot(snapshot)
        self.endpoint_snapshot_changed.emit(snapshot)

    def render_endpoint_snapshot(
        self,
        snapshot: EndpointObservationSnapshot,
    ) -> None:
        """Render the generic tree projection of one committed snapshot."""

        servers = [BaseServerInfo.from_response(response) for response in snapshot.responses]

        def _rebuild_contents() -> None:
            self.populate_tree(servers)
            for observation in snapshot.startup_observations:
                self.server_tree.addTopLevelItem(self.startup_endpoint_tree_item(observation))

        self._tree_rebuild_coordinator.rebuild(self.server_tree, _rebuild_contents)

    def startup_endpoint_tree_item(
        self,
        observation: StartingEndpointObservation,
    ) -> QTreeWidgetItem:
        """Render a row before the endpoint can identify its server role."""

        item = QTreeWidgetItem(
            [
                f"Port {observation.port} - Endpoint",
                "🚀 Starting",
                observation.status.message,
            ]
        )
        item.setData(0, Qt.ItemDataRole.UserRole, observation)
        return item

    @pyqtSlot(bool, str)
    def _on_kill_complete(self, success: bool, message: str) -> None:
        if not success:
            QMessageBox.warning(self, "Kill Failed", message)
        QTimer.singleShot(200, self.refresh_servers)

    def _periodic_cleanup(self) -> None:
        self.periodic_domain_cleanup()

    def _collect_selected_server_ports(self, empty_selection_message: str) -> list[int]:
        selected_items = self.server_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", empty_selection_message)
            return []

        ports_to_kill: list[int] = []
        for item in selected_items:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, (BaseServerInfo, StartingEndpointObservation)):
                ports_to_kill.append(data.port)

        if not ports_to_kill:
            QMessageBox.warning(self, "No Servers", "No servers selected (only workers selected).")
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
        ports: list[int],
        kind: KillOperationKind,
    ) -> None:
        def _kill_servers() -> None:
            def _publish_endpoint_terminated(port: int) -> None:
                if not self._lifecycle_state.is_cleaning_up():
                    self.endpoint_terminated.emit(port)

            success, message = self.execute_kill_operation(
                ports=ports,
                kind=kind,
                on_endpoint_terminated=_publish_endpoint_terminated,
            )
            if not self._lifecycle_state.is_cleaning_up():
                self._kill_complete.emit(success, message)

        spawn_thread_with_context(_kill_servers, name=kind.thread_name)

    def quit_selected_servers(self) -> None:
        ports_to_kill = self._collect_selected_server_ports("Please select servers to quit.")
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

        self._spawn_server_kill_thread(ports_to_kill, KillOperationKind.GRACEFUL)

    def force_kill_selected_servers(self) -> None:
        ports_to_kill = self._collect_selected_server_ports("Please select servers to force kill.")
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

        self._spawn_server_kill_thread(ports_to_kill, KillOperationKind.FORCE)

    def _on_item_double_clicked(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        ancestor = item.parent()
        while not isinstance(data, BaseServerInfo) and ancestor is not None:
            data = ancestor.data(0, Qt.ItemDataRole.UserRole)
            ancestor = ancestor.parent()

        server_info = data if isinstance(data, BaseServerInfo) else None
        log_file = server_info.log_file_path if server_info is not None else None
        if log_file and Path(log_file).exists():
            self.log_file_opened.emit(log_file)
            return
        QMessageBox.information(
            self,
            "No Log File",
            (
                "No log file available for this item.\n\n"
                f"Port: {server_info.port if server_info is not None else 'unknown'}"
            ),
        )

    @abstractmethod
    def populate_tree(self, parsed_servers: list[BaseServerInfo]) -> None:
        """Build tree items from parsed server payloads."""

    @abstractmethod
    def periodic_domain_cleanup(self) -> None:
        """Run domain-specific cleanup on timer ticks."""

    @abstractmethod
    def execute_kill_operation(
        self,
        *,
        ports: list[int],
        kind: KillOperationKind,
        on_endpoint_terminated: Callable[[int], None],
    ) -> tuple[bool, str]:
        """Execute blocking kill operation for selected ports."""

    @abstractmethod
    def on_browser_shown(self) -> None:
        """Domain hook when widget becomes visible."""

    @abstractmethod
    def on_browser_hidden(self) -> None:
        """Domain hook when widget is hidden."""

    @abstractmethod
    def on_browser_cleanup(self) -> None:
        """Domain hook when widget is cleaned up."""
