"""Safe Qt window screenshot capture for UI automation and agent integrations."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QWidget

QtWindowCaptureCallable = Callable[[QWidget], QPixmap]


def _widget_pixmap(widget: QWidget) -> QPixmap:
    """Render the exact requested widget without sampling desktop pixels."""

    return widget.grab()


def _window_pixmap(widget: QWidget) -> QPixmap:
    """Render the requested widget's owning Qt window."""

    return widget.window().grab()


class WindowSnapshotCaptureScope(StrEnum):
    """Safe Qt-rendered screenshot scopes with declaration-owned capture logic."""

    WIDGET = ("widget", _widget_pixmap)
    WINDOW = ("window", _window_pixmap)

    def __new__(
        cls,
        value: str,
        capture: QtWindowCaptureCallable,
    ) -> WindowSnapshotCaptureScope:
        member = str.__new__(cls, value)
        member._value_ = value
        member._capture = capture
        return member

    def capture(self, widget: QWidget) -> QPixmap:
        """Capture through this member's Qt-rendered pixel authority."""

        return self._capture(widget)


@dataclass(frozen=True, kw_only=True)
class WindowSnapshotCaptureSpec:
    """Requested destination and safe Qt-rendered capture scope."""

    output_dir_path: str
    capture_scope: WindowSnapshotCaptureScope = WindowSnapshotCaptureScope.WIDGET

    def same_capture_contract(self, other: WindowSnapshotCaptureSpec) -> bool:
        """Return whether two snapshot carriers request the same capture."""

        return (
            self.output_dir_path == other.output_dir_path
            and self.capture_scope is other.capture_scope
        )


@dataclass(frozen=True, slots=True)
class QtWindowSnapshot:
    """Saved screenshot metadata."""

    uri: str
    path: str
    title: str
    mime_type: str
    width: int
    height: int
    size_bytes: int
    sha256: str
    capture: WindowSnapshotCaptureSpec


@dataclass(frozen=True, slots=True)
class QtWindowSnapshotRequest:
    """Typed request for saving one Qt window or widget screenshot."""

    widget: QWidget
    capture: WindowSnapshotCaptureSpec
    subject_id: str
    title: str


class QtWindowSnapshotService:
    """Capture Qt-rendered widget/window pixels to bounded file artifacts."""

    MIME_TYPE = "image/png"
    FILE_EXTENSION = ".png"
    SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")

    def capture(self, request: QtWindowSnapshotRequest) -> QtWindowSnapshot:
        """Render and persist one screenshot from the requested Qt owner."""

        pixmap = request.capture.capture_scope.capture(request.widget)
        if pixmap.isNull():
            raise RuntimeError(
                f"Qt screenshot capture returned an empty pixmap for {request.subject_id!r}."
            )

        output_dir = Path(request.capture.output_dir_path).expanduser().resolve(strict=False)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / self._filename(request)
        if not pixmap.save(str(output_path), "PNG"):
            raise RuntimeError(f"Failed to save Qt screenshot to {output_path}.")

        image_bytes = output_path.read_bytes()
        digest = hashlib.sha256(image_bytes).hexdigest()
        return QtWindowSnapshot(
            uri=output_path.as_uri(),
            path=str(output_path),
            title=request.title,
            mime_type=self.MIME_TYPE,
            width=pixmap.width(),
            height=pixmap.height(),
            size_bytes=len(image_bytes),
            sha256=digest,
            capture=request.capture,
        )

    def _filename(self, request: QtWindowSnapshotRequest) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        subject = self._safe_filename_token(request.subject_id)
        title = self._safe_filename_token(request.title)
        return f"{timestamp}_{subject}_{title}{self.FILE_EXTENSION}"

    def _safe_filename_token(self, value: str) -> str:
        stripped = value.strip()
        normalized = stripped if stripped else "window"
        token = self.SAFE_FILENAME_PATTERN.sub("_", normalized).strip("._")
        return token[:80] if token else "window"
