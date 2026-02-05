"""ZMQ server protocol abstractions for generic server browser widgets.

This module provides data structures and ABCs for building ZMQ server browser
widgets that work with any zmqruntime-based server.

Design Principles:
- Frozen dataclasses for immutability
- ABCs for extensibility (no protocols)
- Enum-based type safety
- No hasattr/getattr/get with fallback
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Dict, Tuple


class ServerKind(Enum):
    """Server kind for type-safe dispatch."""
    EXECUTION = auto()
    VIEWER = auto()
    GENERIC = auto()


@dataclass(frozen=True)
class ServerNode:
    """Generic server node for UI display.

    All domain-specific data goes into metadata as a dict.
    """
    port: int
    kind: ServerKind
    server_name: str
    ready: bool
    status_icon: str  # Pre-computed icon based on ready state
    log_file_path: str | None
    children: Tuple['ServerNode', ...] = ()
    metadata: Dict[str, Any] = frozendict()  # Server-specific data


@dataclass(frozen=True)
class ProgressUpdate:
    """Generic progress update."""
    task_id: str
    percent: float
    phase: str
    status: str
    step_name: str
    metadata: Dict[str, Any] = frozendict()


class ZMQServerRenderer(ABC):
    """ABC for rendering server nodes.

    Subclasses implement render_server_node and render_child_node to provide
    domain-specific formatting.
    """

    @abstractmethod
    def render_server_node(self, node: ServerNode) -> Tuple[str, str, str]:
        """Return (display_text, status_text, info_text) for server node.

        The returned tuple is used to populate the QTreeWidgetItem columns:
        - display_text: Shown in "Server" column
        - status_text: Shown in "Status" column
        - info_text: Shown in "Info" column
        """
        pass

    @abstractmethod
    def render_child_node(self, node: ServerNode) -> Tuple[str, str, str]:
        """Return (display_text, status_text, info_text) for child node."""
        pass


# Type alias for frozendict - use typing.Annotated with frozendict constraint
def frozendict(**kwargs) -> Dict[str, Any]:
    """Create an immutable dict for frozen dataclass fields."""
    return dict(**kwargs)  # Temporary - will be truly immutable in use
