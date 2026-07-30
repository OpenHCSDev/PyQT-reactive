"""Nominal UI projections of typed ZMQ server heartbeats."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import ClassVar

from metaclass_registry import AutoRegisterMeta
from zmqruntime.messages import (
    PongResponse,
    QueuedExecutionInfo,
    RunningExecutionInfo,
    ServerRole,
    WorkerState,
)


@dataclass(frozen=True, slots=True)
class BaseServerInfo(ABC, metaclass=AutoRegisterMeta):
    """Base presentation view over the authoritative PONG response."""

    __registry_key__ = "_server_role"
    _server_role: ClassVar[ServerRole | None] = None

    response: PongResponse

    @classmethod
    def from_response(cls, response: PongResponse) -> BaseServerInfo:
        """Construct the nominal projection registered for the response role."""

        info_type = cls.__registry__[response.server_role]
        return info_type(response)

    @property
    def port(self) -> int:
        return self.response.port

    @property
    def ready(self) -> bool:
        return self.response.ready

    @property
    def log_file_path(self) -> str | None:
        return self.response.log_file_path

    @property
    def server_name(self) -> str:
        return self.response.server

    def tree_item_key(self) -> str:
        return f"port:{self.port}"


@dataclass(frozen=True, slots=True)
class ExecutionServerInfo(BaseServerInfo):
    """Execution server specific fields."""

    _server_role = ServerRole.EXECUTION

    @property
    def workers(self) -> tuple[WorkerState, ...]:
        return self.response.workers or ()

    @property
    def running_execution_entries(self) -> tuple[RunningExecutionInfo, ...]:
        return self.response.running_executions or ()

    @property
    def queued_execution_entries(self) -> tuple[QueuedExecutionInfo, ...]:
        return self.response.queued_executions or ()

    @property
    def running_executions(self) -> tuple[str, ...]:
        return tuple(entry.execution_id for entry in self.running_execution_entries)

    @property
    def queued_executions(self) -> tuple[str, ...]:
        return tuple(entry.execution_id for entry in self.queued_execution_entries)


@dataclass(frozen=True, slots=True)
class ViewerServerInfo(BaseServerInfo):
    """Viewer server (napari/fiji) fields."""

    _server_role = ServerRole.VIEWER

    @property
    def viewer_name(self) -> str:
        return self.response.server_type or self.response.server

    @property
    def memory_mb(self) -> float | None:
        usage = self.response.process_usage
        return None if usage is None else usage.memory_mb

    @property
    def cpu_percent(self) -> float | None:
        usage = self.response.process_usage
        return None if usage is None else usage.cpu_percent


@dataclass(frozen=True, slots=True)
class GenericServerInfo(BaseServerInfo):
    """Fallback view for servers without a specialized presentation role."""

    _server_role = ServerRole.GENERIC
