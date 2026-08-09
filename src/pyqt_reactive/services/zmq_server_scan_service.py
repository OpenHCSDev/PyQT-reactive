"""Typed ZMQ server discovery."""

from __future__ import annotations

import concurrent.futures
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from zmqruntime.config import TransportMode, ZMQConfig
from zmqruntime.messages import PongResponse
from zmqruntime.startup import EndpointStartupPhase, EndpointStartupStatus
from zmqruntime.transport import request_control_ping, resolve_transport_mode


class EndpointObservation(ABC):
    """One nominal observation occupying one endpoint port in a snapshot."""

    @property
    @abstractmethod
    def port(self) -> int:
        """Observed endpoint port."""

    @property
    @abstractmethod
    def status(self) -> EndpointStartupStatus:
        """Lifecycle status derived from this observation."""

    @property
    @abstractmethod
    def response(self) -> PongResponse | None:
        """Typed heartbeat when this observation reached the control endpoint."""

    @property
    @abstractmethod
    def startup_observation(self) -> StartingEndpointObservation | None:
        """Startup-row projection when the control endpoint is not ready."""

    @abstractmethod
    def after_startup_status(
        self,
        status: EndpointStartupStatus,
    ) -> EndpointObservation | None:
        """Return the observation after a newer lifecycle event."""

    @abstractmethod
    def retained_after_scan_miss(
        self,
        is_proven_live: Callable[[PongResponse], bool],
    ) -> EndpointObservation | None:
        """Return this observation only when its declaration proves retention."""


@dataclass(frozen=True, slots=True)
class ResponsiveEndpointObservation(EndpointObservation):
    """Endpoint observation backed by its canonical PONG response."""

    pong: PongResponse

    @property
    def port(self) -> int:
        return self.pong.port

    @property
    def status(self) -> EndpointStartupStatus:
        if self.pong.ready:
            return EndpointStartupStatus(
                phase=EndpointStartupPhase.CONNECTED,
                message="Connected",
            )
        return EndpointStartupStatus(
            phase=EndpointStartupPhase.CHECKING_ENDPOINT,
            message="Starting",
        )

    @property
    def response(self) -> PongResponse:
        return self.pong

    @property
    def startup_observation(self) -> None:
        return None

    def after_startup_status(
        self,
        status: EndpointStartupStatus,
    ) -> EndpointObservation | None:
        return self if status.phase.expects_endpoint_presence else None

    def retained_after_scan_miss(
        self,
        is_proven_live: Callable[[PongResponse], bool],
    ) -> EndpointObservation | None:
        return self if is_proven_live(self.pong) else None


@dataclass(frozen=True, slots=True)
class StartingEndpointObservation(EndpointObservation):
    """Endpoint attempt observed before its control endpoint answers PING."""

    endpoint_port: int
    startup_status: EndpointStartupStatus

    def __post_init__(self) -> None:
        if not self.startup_status.phase.expects_endpoint_presence:
            raise ValueError("Starting endpoint observation requires an active phase")

    @property
    def port(self) -> int:
        return self.endpoint_port

    @property
    def status(self) -> EndpointStartupStatus:
        return self.startup_status

    @property
    def response(self) -> None:
        return None

    @property
    def startup_observation(self) -> StartingEndpointObservation:
        return self

    def after_startup_status(
        self,
        status: EndpointStartupStatus,
    ) -> EndpointObservation | None:
        if not status.phase.expects_endpoint_presence:
            return None
        return type(self)(endpoint_port=self.port, startup_status=status)

    def retained_after_scan_miss(
        self,
        is_proven_live: Callable[[PongResponse], bool],
    ) -> EndpointObservation | None:
        del is_proven_live
        return self


@dataclass(frozen=True, slots=True)
class EndpointObservationSnapshot:
    """One immutable authority for every currently observable endpoint."""

    observations: tuple[EndpointObservation, ...] = ()

    @classmethod
    def from_observations(
        cls,
        observations: Sequence[EndpointObservation],
    ) -> EndpointObservationSnapshot:
        """Canonicalize one observation per port into stable port order."""

        by_port = {observation.port: observation for observation in observations}
        return cls(tuple(by_port[port] for port in sorted(by_port)))

    @classmethod
    def from_responses(
        cls,
        responses: Sequence[PongResponse],
    ) -> EndpointObservationSnapshot:
        """Canonicalize scan results into stable port order."""

        return cls.from_observations(
            tuple(ResponsiveEndpointObservation(response) for response in responses)
        )

    @property
    def responses(self) -> tuple[PongResponse, ...]:
        """Project responsive heartbeat payloads from the endpoint authority."""

        return tuple(
            response
            for observation in self.observations
            if (response := observation.response) is not None
        )

    @property
    def startup_observations(self) -> tuple[StartingEndpointObservation, ...]:
        """Project startup rows from the endpoint authority."""

        return tuple(
            startup_observation
            for observation in self.observations
            if (startup_observation := observation.startup_observation) is not None
        )

    def with_startup_status(
        self,
        port: int,
        status: EndpointStartupStatus,
    ) -> EndpointObservationSnapshot:
        """Apply one newer startup event to this endpoint authority."""

        by_port = {observation.port: observation for observation in self.observations}
        current = by_port.get(port)
        if current is None:
            replacement = (
                StartingEndpointObservation(port, status)
                if status.phase.expects_endpoint_presence
                else None
            )
        else:
            replacement = current.after_startup_status(status)
        if replacement is None:
            by_port.pop(port, None)
        else:
            by_port[port] = replacement
        return self.from_observations(tuple(by_port.values()))

    def retain_proven_live_from(
        self,
        previous: EndpointObservationSnapshot,
        is_proven_live: Callable[[PongResponse], bool],
    ) -> EndpointObservationSnapshot:
        """Reconcile scan misses through each nominal observation's proof rule."""

        observed_ports = {observation.port for observation in self.observations}
        retained = tuple(
            retained_observation
            for observation in previous.observations
            if observation.port not in observed_ports
            if (retained_observation := observation.retained_after_scan_miss(is_proven_live))
            is not None
        )
        return self.from_observations((*self.observations, *retained))

    def status_for_port(self, port: int) -> EndpointStartupStatus:
        """Derive endpoint presentation from this snapshot without stored flags."""

        observation = next(
            (observation for observation in self.observations if observation.port == port),
            None,
        )
        if observation is None:
            return EndpointStartupStatus(
                phase=EndpointStartupPhase.DISCONNECTED,
                message="Not connected",
            )
        return observation.status


@dataclass(frozen=True, slots=True)
class EndpointScanResult:
    """One scan result tied to the immutable authority it began from."""

    snapshot: EndpointObservationSnapshot
    base_snapshot: EndpointObservationSnapshot


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

    def scan_ports(
        self,
        ports: Sequence[int],
        *,
        previous_snapshot: EndpointObservationSnapshot | None = None,
    ) -> EndpointObservationSnapshot:
        """Ping all provided ports in parallel."""

        responses: list[PongResponse] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = tuple(executor.submit(self.ping_server, port) for port in ports)
            for future in concurrent.futures.as_completed(futures):
                response = future.result()
                if response is not None:
                    responses.append(response)
        observed = EndpointObservationSnapshot.from_responses(responses)
        if previous_snapshot is None:
            return observed
        return observed.retain_proven_live_from(
            previous_snapshot,
            self._is_proven_live,
        )

    def _is_proven_live(self, response: PongResponse) -> bool:
        identity = response.process_identity
        return (
            identity is not None
            and self.transport_mode.endpoint_is_local(self.host, response.port)
            and identity.is_alive() is True
        )

    def ping_server(self, port: int) -> PongResponse | None:
        """Return the authoritative typed heartbeat for one server."""

        return request_control_ping(
            port,
            self.transport_mode,
            host=self.host,
            config=self.config,
            timeout_ms=self.timeout_ms,
        )
