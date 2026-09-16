"""Safe Qt window screenshot capture for UI automation and agent integrations."""

from __future__ import annotations

import hashlib
import re
import time
from math import isfinite
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING
from python_introspect import project_dataclass

from ..flash_trace import (
    FlashTrace,
    FlashTraceRecord,
)


if TYPE_CHECKING:
    from PyQt6.QtGui import QPixmap
    from PyQt6.QtWidgets import QWidget

QtWindowCaptureCallable = Callable[["QWidget"], "QPixmap"]


@dataclass(frozen=True, slots=True)
class FlashPaintElement:
    """One source actually painted, in owning-window coordinates."""

    key: str
    source_token: str
    rect: tuple[int, int, int, int]
    rgba: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class FlashPaintFrame:
    """Receipt emitted after the flash painter has ended."""

    window_identity: int
    painted_at_monotonic: float
    configured_maximum_alpha: int
    configured_flash_duration_s: float
    elements: tuple[FlashPaintElement, ...]

    @property
    def has_maximum_alpha(self) -> bool:
        return any(element.rgba[3] == self.configured_maximum_alpha for element in self.elements)


def _maximum_alpha_frame(frame: FlashPaintFrame) -> bool:
    return frame.has_maximum_alpha


def _no_frame(frame: FlashPaintFrame) -> bool:
    return False


class WindowSnapshotFrameCondition(StrEnum):
    """Closed capture conditions evaluated from real renderer receipts."""

    IMMEDIATE = ("immediate", False, _no_frame, False, False)
    FLASH_MAXIMUM_ALPHA = ("flash_maximum_alpha", True, _maximum_alpha_frame, False, True)
    NO_FLASH = ("no_flash", True, _no_frame, True, False)

    def __new__(cls, value, observes, accepts_frame, accepts_quiet, requests_native_render):
        member = str.__new__(cls, value)
        member._value_ = value
        member.observes = observes
        member._accepts_frame = accepts_frame
        member.accepts_quiet = accepts_quiet
        member.requests_native_render = requests_native_render
        return member

    def accepts_frame(self, frame: FlashPaintFrame) -> bool:
        return self._accepts_frame(frame)

    def accepts_timeout(self, starts: int, frames: int) -> bool:
        return self.accepts_quiet and starts == 0 and frames == 0


@dataclass(frozen=True, slots=True)
class WindowVisualObservation:
    """Actual target-window activity during one armed observation."""

    condition: WindowSnapshotFrameCondition
    window_identity: int
    started_at_monotonic: float
    completed_at_monotonic: float
    configured_flash_duration_s: float
    baseline_inactive: bool
    flash_start_count: int
    painted_frame_count: int
    frame: FlashPaintFrame | None = None
    # Failure diagnostics reuse the existing bounded process-local trace ring.
    # These contextual records are not asserted to be target-window-only.
    trace: tuple[FlashTraceRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class WindowSnapshotObservationFailure:
    """Failed observation with its actual activity evidence preserved."""

    error: Exception
    observation: WindowVisualObservation


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
    frame_condition: WindowSnapshotFrameCondition = WindowSnapshotFrameCondition.IMMEDIATE
    observation_timeout_s: float = 5.0

    def __post_init__(self) -> None:
        if not isfinite(self.observation_timeout_s) or not 0 < self.observation_timeout_s <= 30:
            raise ValueError("observation_timeout_s must be finite and in (0, 30].")

    def same_capture_contract(self, other: WindowSnapshotCaptureSpec) -> bool:
        """Return whether two snapshot carriers request the same capture."""

        return (project_dataclass(WindowSnapshotCaptureSpec, self)
                == project_dataclass(WindowSnapshotCaptureSpec, other))


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
    observation: WindowVisualObservation | None = None


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

    def observe(
        self,
        request: QtWindowSnapshotRequest,
        completed: Callable[[QtWindowSnapshot], None],
        failed: Callable[[WindowSnapshotObservationFailure], None],
    ) -> None:
        """Arm a bounded real-renderer observation without blocking UI mutations."""
        _WindowSnapshotObservation(self, request, completed, failed)

    def capture(
        self, request: QtWindowSnapshotRequest,
        observation: WindowVisualObservation | None = None,
    ) -> QtWindowSnapshot:
        """Render and persist one screenshot from the requested Qt owner."""

        pixmap = request.capture.capture_scope.capture(request.widget)
        return self._persist(request, pixmap, observation)

    def _persist(
        self, request: QtWindowSnapshotRequest, pixmap: QPixmap,
        observation: WindowVisualObservation | None = None,
    ) -> QtWindowSnapshot:
        """Persist the same native render whose receipt was observed."""
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
            observation=observation,
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


class _WindowSnapshotObservation:
    """Qt-owned timer/signal lifecycle for an armed capture, not a job registry."""

    def __init__(self, service, request, completed, failed):
        from PyQt6.QtCore import QTimer, Qt
        from pyqt_reactive.animation.flash_mixin import WindowFlashOverlay

        self.service, self.request = service, request
        self.completed, self.failed = completed, failed
        self.condition = request.capture.frame_condition
        if not self.condition.observes:
            raise ValueError("Immediate snapshots do not require observation.")
        self.overlay = WindowFlashOverlay.get_for_window(request.widget)
        if not isinstance(self.overlay, WindowFlashOverlay):
            raise ValueError("This window has no supported flash-painter observation owner.")
        self.config = self.overlay.flash_observation_config()
        if request.capture.observation_timeout_s < self.config.total_duration_s:
            raise ValueError("Observation timeout must cover the configured flash interval.")
        if self.overlay.has_pending_or_active_flash():
            raise ValueError("Flash observation requires an inactive target-window baseline.")
        self.started = time.perf_counter()
        self.window_identity = id(request.widget.window())
        self.starts = self.frames = 0
        self.closed = False
        self.rendering = False
        self.rendered_frame = None
        self.last_painted_frame = None
        self.timer = QTimer(self.overlay)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setSingleShot(True)
        # Qt weakly references bound Python slots. The owned timer's connection
        # retains this observation until completion or parent destruction.
        self.timer.timeout.connect(lambda: self._timeout())
        self.start_signal = self.overlay.flash_start_signal()
        self.start_signal.connect(self._started)
        self.overlay.frame_painted.connect(self._painted)
        if self.condition.requests_native_render:
            self.overlay.native_render_requested.connect(self._render_current_frame)
        self.overlay.destroyed.connect(self._destroyed)
        self.timer.start(int(request.capture.observation_timeout_s * 1000 + 0.999))

    def _started(self, window_identity, keys):
        if window_identity == self.window_identity:
            self.starts += len(keys)

    def _painted(self, frame):
        self.frames += 1
        self.last_painted_frame = frame
        if self.rendering and self.condition.accepts_frame(frame):
            self.rendered_frame = frame

    def _render_current_frame(self):
        if self.closed or self.rendering:
            return
        self.rendering = True
        self.rendered_frame = None
        try:
            pixmap = self.request.capture.capture_scope.capture(self.request.widget)
        except Exception as exc:
            self._close()
            self.failed(WindowSnapshotObservationFailure(exc, self._receipt(failure=True)))
            return
        finally:
            self.rendering = False
        if self.rendered_frame is not None:
            self._finish(self.rendered_frame, pixmap)

    def _receipt(self, frame=None, *, failure=False):
        return WindowVisualObservation(
            condition=self.condition,
            window_identity=self.window_identity,
            started_at_monotonic=self.started,
            completed_at_monotonic=time.perf_counter(),
            configured_flash_duration_s=self.config.total_duration_s,
            baseline_inactive=True,
            flash_start_count=self.starts,
            painted_frame_count=self.frames,
            frame=self.last_painted_frame if failure else frame,
            trace=FlashTrace.recent() if failure else (),
        )

    def _timeout(self):
        if self.condition.accepts_timeout(self.starts, self.frames):
            self._finish()
        else:
            self._close()
            self.failed(WindowSnapshotObservationFailure(TimeoutError(
                f"Requested {self.condition.value} was not observed; "
                f"target flash starts={self.starts}, painted frames={self.frames}."
            ), self._receipt(failure=True)))

    def _finish(self, frame=None, pixmap=None):
        receipt = self._receipt(frame)
        # An observed frame belongs to the supplied grab, which has returned.
        # Quiet captures still use the ordinary native capture after disarming.
        self._close()
        try:
            snapshot = (self.service.capture(self.request, receipt) if pixmap is None
                        else self.service._persist(self.request, pixmap, receipt))
        except Exception as exc:
            self.failed(WindowSnapshotObservationFailure(exc, receipt))
        else:
            self.completed(snapshot)

    def _close(self):
        if self.closed:
            return
        self.closed = True
        self.timer.stop()
        self.timer.timeout.disconnect()
        self.start_signal.disconnect(self._started)
        self.overlay.frame_painted.disconnect(self._painted)
        if self.condition.requests_native_render:
            self.overlay.native_render_requested.disconnect(self._render_current_frame)
        self.overlay.destroyed.disconnect(self._destroyed)
        self.timer.deleteLater()

    def _destroyed(self):
        self.closed = True
        self.start_signal.disconnect(self._started)
        self.failed(WindowSnapshotObservationFailure(
            RuntimeError("Observed window was destroyed before capture."), self._receipt(failure=True),
        ))
