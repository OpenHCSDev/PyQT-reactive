"""Typed parsing for ZMQ server ping payloads."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Mapping

from zmqruntime.messages import WorkerState


class ServerKind(Enum):
    """Server kind for type-safe dispatch."""

    EXECUTION = auto()
    NAPARI = auto()
    FIJI = auto()
    GENERIC = auto()


@dataclass(frozen=True)
class CompileStatus:
    """Execution-server compile status parsed from ping payload."""

    status_text: str
    is_success: bool
    is_failed: bool
    message: str

    @classmethod
    def from_payload(
        cls, compile_status: str, compile_message: str
    ) -> "CompileStatus":
        normalized = compile_status.lower()
        return cls(
            status_text=compile_status,
            is_success="success" in normalized,
            is_failed="failed" in normalized,
            message=compile_message,
        )


@dataclass(frozen=True)
class RunningExecutionEntry:
    """Running execution row from server ping payload."""

    execution_id: str
    plate_id: str
    start_time: float | None = None
    elapsed: float | None = None
    compile_only: bool = False


@dataclass(frozen=True)
class QueuedExecutionEntry:
    """Queued execution row from server ping payload."""

    execution_id: str
    plate_id: str
    queue_position: int


@dataclass(frozen=True)
class BaseServerInfo(ABC):
    """Base typed server ping view."""

    raw: dict[str, Any]
    port: int
    ready: bool
    log_file: str | None

    @property
    @abstractmethod
    def kind(self) -> ServerKind:
        """Server kind."""


@dataclass(frozen=True)
class ExecutionServerInfo(BaseServerInfo):
    """Execution server specific fields."""

    workers: tuple[WorkerState, ...] = ()
    compile_status: CompileStatus | None = None
    running_execution_entries: tuple[RunningExecutionEntry, ...] = ()
    queued_execution_entries: tuple[QueuedExecutionEntry, ...] = ()

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ExecutionServerInfo":
        running_raw = payload["running_executions"]
        queued_raw = payload["queued_executions"]
        workers_raw = payload["workers"]

        compile_status = None
        if "compile_status" in payload:
            compile_message = ""
            if "compile_message" in payload:
                compile_message = str(payload["compile_message"])
            compile_status = CompileStatus.from_payload(
                str(payload["compile_status"]),
                compile_message,
            )

        return cls(
            raw=dict(payload),
            port=int(payload["port"]),
            ready=bool(payload["ready"]),
            log_file=str(payload["log_file_path"])
            if "log_file_path" in payload and payload["log_file_path"] is not None
            else None,
            workers=tuple(WorkerState.from_dict(worker) for worker in workers_raw),
            compile_status=compile_status,
            running_execution_entries=tuple(
                RunningExecutionEntry(
                    execution_id=str(execution["execution_id"]),
                    plate_id=str(execution["plate_id"]),
                    start_time=float(execution["start_time"])
                    if "start_time" in execution and execution["start_time"] is not None
                    else None,
                    elapsed=float(execution["elapsed"])
                    if "elapsed" in execution and execution["elapsed"] is not None
                    else None,
                    compile_only=bool(execution.get("compile_only", False)),
                )
                for execution in running_raw
            ),
            queued_execution_entries=tuple(
                QueuedExecutionEntry(
                    execution_id=str(execution["execution_id"]),
                    plate_id=str(execution["plate_id"]),
                    queue_position=int(execution["queue_position"]),
                )
                for execution in queued_raw
            ),
        )

    @property
    def kind(self) -> ServerKind:
        return ServerKind.EXECUTION

    @property
    def running_executions(self) -> tuple[str, ...]:
        return tuple(entry.execution_id for entry in self.running_execution_entries)

    @property
    def queued_executions(self) -> tuple[str, ...]:
        return tuple(entry.execution_id for entry in self.queued_execution_entries)


@dataclass(frozen=True)
class ViewerServerInfo(BaseServerInfo):
    """Viewer server (napari/fiji) fields."""

    viewer_kind: ServerKind
    memory_mb: float | None = None
    cpu_percent: float | None = None

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        viewer_kind: ServerKind,
    ) -> "ViewerServerInfo":
        memory_mb = None
        if "memory_mb" in payload and payload["memory_mb"] is not None:
            memory_mb = float(payload["memory_mb"])
        cpu_percent = None
        if "cpu_percent" in payload and payload["cpu_percent"] is not None:
            cpu_percent = float(payload["cpu_percent"])

        return cls(
            raw=dict(payload),
            port=int(payload["port"]),
            ready=bool(payload["ready"]),
            viewer_kind=viewer_kind,
            log_file=str(payload["log_file_path"])
            if "log_file_path" in payload and payload["log_file_path"] is not None
            else None,
            memory_mb=memory_mb,
            cpu_percent=cpu_percent,
        )

    @property
    def kind(self) -> ServerKind:
        return self.viewer_kind


@dataclass(frozen=True)
class GenericServerInfo(BaseServerInfo):
    """Fallback type for unknown server names."""

    server_name: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "GenericServerInfo":
        return cls(
            raw=dict(payload),
            port=int(payload["port"]),
            ready=bool(payload["ready"]),
            server_name=str(payload["server"]),
            log_file=str(payload["log_file_path"])
            if "log_file_path" in payload and payload["log_file_path"] is not None
            else None,
        )

    @property
    def kind(self) -> ServerKind:
        return ServerKind.GENERIC


class ServerInfoParserABC(ABC):
    """ABC for parsing ping payloads into typed server info."""

    @abstractmethod
    def parse(self, payload: Mapping[str, Any]) -> BaseServerInfo:
        """Parse ping payload."""


class DefaultServerInfoParser(ServerInfoParserABC):
    """Default parser based on server class-name conventions."""

    def parse(self, payload: Mapping[str, Any]) -> BaseServerInfo:
        server_name = str(payload["server"])
        if server_name.endswith("ExecutionServer"):
            return ExecutionServerInfo.from_payload(payload)
        if "Napari" in server_name:
            return ViewerServerInfo.from_payload(payload, ServerKind.NAPARI)
        if "Fiji" in server_name:
            return ViewerServerInfo.from_payload(payload, ServerKind.FIJI)
        return GenericServerInfo.from_payload(payload)
