"""Typed ZMQ server discovery."""

from __future__ import annotations

import concurrent.futures
from collections.abc import Sequence

from zmqruntime.config import TransportMode, ZMQConfig
from zmqruntime.messages import PongResponse
from zmqruntime.transport import request_control_ping, resolve_transport_mode


class ZMQServerScanService:
    """Scan server endpoints while preserving the canonical PONG type."""

    def __init__(
        self,
        *,
        config: ZMQConfig,
        host: str = "localhost",
        transport_mode: TransportMode | None = None,
        timeout_ms: int = 300,
        max_workers: int = 10,
    ) -> None:
        self.config = config
        self.host = host
        self.transport_mode = resolve_transport_mode(transport_mode)
        self.timeout_ms = timeout_ms
        self.max_workers = max_workers

    def scan_ports(self, ports: Sequence[int]) -> list[PongResponse]:
        """Ping all provided ports in parallel."""

        responses: list[PongResponse] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = tuple(executor.submit(self.ping_server, port) for port in ports)
            for future in concurrent.futures.as_completed(futures):
                response = future.result()
                if response is not None:
                    responses.append(response)
        return responses

    def ping_server(self, port: int) -> PongResponse | None:
        """Return the authoritative typed heartbeat for one server."""

        return request_control_ping(
            port,
            self.transport_mode,
            host=self.host,
            config=self.config,
            timeout_ms=self.timeout_ms,
        )
