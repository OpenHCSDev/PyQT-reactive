"""Generic ZMQ server scan/ping service."""

from __future__ import annotations

import concurrent.futures
import pickle
from typing import Any, Dict, List, Optional

import zmq

from zmqruntime.transport import (
    get_default_transport_mode,
    get_zmq_transport_url,
)


class ZMQServerScanService:
    """Scan ports and collect server ping payloads."""

    def __init__(
        self,
        *,
        control_port_offset: int,
        config,
        host: str = "localhost",
        timeout_ms: int = 300,
        max_workers: int = 10,
    ) -> None:
        self.control_port_offset = control_port_offset
        self.config = config
        self.host = host
        self.timeout_ms = timeout_ms
        self.max_workers = max_workers

    def scan_ports(self, ports: List[int]) -> List[Dict[str, Any]]:
        """Ping all provided ports in parallel and return responsive server payloads."""
        servers: List[Dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_port = {
                executor.submit(self.ping_server, port): port
                for port in ports
            }
            for future in concurrent.futures.as_completed(future_to_port):
                server_info = future.result()
                if server_info is not None:
                    servers.append(server_info)
        return servers

    def ping_server(self, port: int) -> Optional[Dict[str, Any]]:
        """Ping one server data port and return pong payload when available."""
        control_port = port + self.control_port_offset
        control_context = None
        control_socket = None
        try:
            control_context = zmq.Context()
            control_socket = control_context.socket(zmq.REQ)
            control_socket.setsockopt(zmq.LINGER, 0)
            control_socket.setsockopt(zmq.RCVTIMEO, self.timeout_ms)

            transport_mode = get_default_transport_mode()
            control_url = get_zmq_transport_url(
                control_port,
                host=self.host,
                mode=transport_mode,
                config=self.config,
            )
            control_socket.connect(control_url)
            control_socket.send(pickle.dumps({"type": "ping"}))
            response_data = pickle.loads(control_socket.recv())
            if response_data.get("type") != "pong":
                return None
            return response_data
        except Exception:
            return None
        finally:
            if control_socket is not None:
                try:
                    control_socket.close()
                except Exception:
                    pass
            if control_context is not None:
                try:
                    control_context.term()
                except Exception:
                    pass
