"""Generic code-document capability for WindowManager-managed windows."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass

PYTHON_MIME_TYPE = "text/x-python"


class WindowCodeDocumentError(RuntimeError):
    """Raised when a managed window cannot service a code-document request."""


@dataclass(frozen=True, slots=True)
class WindowCodeDocument:
    """Rendered code document owned by one managed window."""

    title: str
    source: str
    mime_type: str = PYTHON_MIME_TYPE


class WindowCodeDocumentDriver(ABC):
    """Read/apply code-mode content for one WindowManager scope."""

    def current_revision_token(self) -> str:
        """Return the revision of the authoritative clean document content."""
        source = self.read_document(clean=True).source
        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    def records_object_state_snapshot_on_apply(self) -> bool:
        """Return whether applying this document must advance ObjectState history."""
        return True

    @abstractmethod
    def read_document(self, clean: bool = True) -> WindowCodeDocument:
        """Return the current code document."""
        raise NotImplementedError

    @abstractmethod
    def validate_source(self, source: str) -> None:
        """Validate source without changing UI state."""
        raise NotImplementedError

    @abstractmethod
    def apply_source(self, source: str) -> None:
        """Apply source through the same state path as interactive code mode."""
        raise NotImplementedError
