"""Generic ZMQ server browser widget with domain hooks."""

from __future__ import annotations

import logging
from abc import ABC, ABCMeta, abstractmethod
from collections.abc import Callable
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
from zmqruntime.shutdown import EndpointShutdownService
from zmqruntime.startup import EndpointStartupStatus

from pyqt_reactive.services.coalesced_scan_requests import CoalescedScanRequests
from pyqt_reactive.services.zmq_server_info import (
    BaseServerInfo,
)
from pyqt_reactive.services.zmq_server_scan_service import (
    EndpointObservationAuthority,
    EndpointObservationSnapshot,
    EndpointObservationTransition,
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


class ZMQServerBrowserWidgetABC(QWidget, ABC, metaclass=_CombinedMeta):
    """Generic ZMQ browser UI infrastructure with domain extension hooks."""

    _TREE_INDENTATION_PX = 12

    endpoint_terminated = pyqtSignal(object)
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

        self.title = title
        self.color_scheme = color_scheme
        self._endpoint_authority = EndpointObservationAuthority(
            scan_service,
            tuple(ports_to_scan),
        )
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

    def replace_scan_declaration(
        self,
        *,
        scan_service: ZMQServerScanService,
        ports_to_scan: list[int],
    ) -> None:
        """Replace scan authority and invalidate rows produced by its predecessor."""

        transition = self._endpoint_authority.with_scan_declaration(
            scan_service,
            ports_to_scan,
        )
        if transition.authority is self._endpoint_authority:
            return
        self._commit_endpoint_authority(transition)
        self.refresh_servers()

    @property
    def _scan_service(self) -> ZMQServerScanService:
        return self._endpoint_authority.scan_service

    @property
    def _endpoint_snapshot(self) -> EndpointObservationSnapshot:
        return self._endpoint_authority.snapshot

    @property
    def _scan_ports(self) -> tuple[int, ...]:
        return self._endpoint_authority.ports

    def _start_server_scan(self) -> None:
        """Run the active coalesced scan request."""

        base_authority = self._endpoint_authority
        previous_snapshot = base_authority.snapshot
        scan_service = base_authority.scan_service
        ports_to_scan = base_authority.ports

        def _scan_and_emit() -> None:
            try:
                snapshot = scan_service.scan_ports(
                    ports_to_scan,
                    previous_snapshot=previous_snapshot,
                )
            except Exception:
                logger.exception("Failed to scan ZMQ server endpoints")
                snapshot = previous_snapshot
            if not self._lifecycle_state.is_cleaning_up():
                self._scan_complete.emit(
                    EndpointScanResult(
                        snapshot=snapshot,
                        base_authority=base_authority,
                    )
                )

        spawn_thread_with_context(_scan_and_emit, name="scan_servers")

    @pyqtSlot(object)
    def _update_server_list(self, result: EndpointScanResult) -> None:
        """Commit one scan authority, then update every derived UI projection."""

        if not isinstance(result, EndpointScanResult):
            raise TypeError("ZMQ browser scan completion requires EndpointScanResult")
        if result.base_authority is self._endpoint_authority:
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

        self._commit_endpoint_authority(self._endpoint_authority.with_snapshot(snapshot))

    def _commit_endpoint_authority(
        self,
        transition: EndpointObservationTransition,
    ) -> None:
        """Commit one indivisible scan declaration and observation state."""

        previous_snapshot = self._endpoint_authority.snapshot
        self._endpoint_authority = transition.authority
        if transition.authority.snapshot != previous_snapshot:
            self.render_endpoint_snapshot(transition.authority.snapshot)
            self.endpoint_snapshot_changed.emit(transition.authority.snapshot)
        for endpoint in transition.terminated_endpoints:
            self.endpoint_terminated.emit(endpoint)

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
        mode: EndpointShutdownMode,
    ) -> None:
        scan_service = self._scan_service
        shutdown_service = EndpointShutdownService.for_endpoint(
            scan_service.config,
            scan_service.endpoint(ports[0]),
        )

        def _kill_servers() -> None:
            result = shutdown_service.shutdown_ports(
                ports=ports,
                mode=mode,
            )
            if not self._lifecycle_state.is_cleaning_up():
                for port in result.terminated_ports:
                    self.endpoint_terminated.emit(scan_service.endpoint(port))
                self._kill_complete.emit(
                    result.succeeded,
                    result.message,
                )

        spawn_thread_with_context(
            _kill_servers,
            name=f"{mode.value}_endpoint_shutdown",
        )

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

        self._spawn_server_kill_thread(
            ports_to_kill,
            EndpointShutdownMode.GRACEFUL,
        )

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

        self._spawn_server_kill_thread(
            ports_to_kill,
            EndpointShutdownMode.FORCE,
        )

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
    def on_browser_shown(self) -> None:
        """Domain hook when widget becomes visible."""

    @abstractmethod
    def on_browser_hidden(self) -> None:
        """Domain hook when widget is hidden."""

    @abstractmethod
    def on_browser_cleanup(self) -> None:
        """Domain hook when widget is cleaned up."""
