"""Safe Qt window screenshot capture for UI automation and agent integrations."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
import re
import time
from math import isfinite
from collections.abc import Callable
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING
from python_introspect import project_dataclass
from zmqruntime.timeouts import OperationDeadline

from ..flash_trace import (
    FlashTrace,
    FlashTraceRecord,
)

if TYPE_CHECKING:
    from PyQt6.QtCore import pyqtBoundSignal
    from PyQt6.QtGui import QPixmap
    from PyQt6.QtWidgets import QWidget
    from PyQt6.QtOpenGLWidgets import QOpenGLWidget

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


def _observe_flash(*args):
    _WindowFlashSnapshotObservation(*args)


def _observe_render(*args):
    _WindowRenderSnapshotObservation(*args)


def _capture_immediate(service, request, completed, failed):
    completed(service.capture(request))


def _validate_render_observation(observation):
    if observation.render_frame is None:
        raise ValueError("Render-complete capture has no native completion receipt.")
    frame = observation.render_frame
    if (
        frame.window_identity != observation.window_identity
        or not observation.started_at_monotonic
        <= frame.completed_at_monotonic
        <= observation.completed_at_monotonic
    ):
        raise ValueError("Native completion receipt is outside this window observation.")


def _validate_visual_observation(observation):
    pass


class WindowSnapshotFrameCondition(StrEnum):
    """Closed capture conditions evaluated from real renderer receipts."""

    IMMEDIATE = (
        "immediate",
        False,
        _no_frame,
        False,
        False,
        _capture_immediate,
        _validate_visual_observation,
    )
    FLASH_MAXIMUM_ALPHA = (
        "flash_maximum_alpha",
        True,
        _maximum_alpha_frame,
        False,
        True,
        _observe_flash,
        _validate_visual_observation,
    )
    NO_FLASH = (
        "no_flash",
        True,
        _no_frame,
        True,
        False,
        _observe_flash,
        _validate_visual_observation,
    )
    RENDER_COMPLETE = (
        "render_complete",
        True,
        _no_frame,
        False,
        False,
        _observe_render,
        _validate_render_observation,
    )

    def __new__(
        cls,
        value,
        observes,
        accepts_frame,
        accepts_quiet,
        requests_native_render,
        observe,
        validate,
    ):
        member = str.__new__(cls, value)
        member._value_ = value
        member.observes = observes
        member._accepts_frame = accepts_frame
        member.accepts_quiet = accepts_quiet
        member.requests_native_render = requests_native_render
        member._observe = observe
        member._validate = validate
        return member

    def accepts_frame(self, frame: FlashPaintFrame) -> bool:
        return self._accepts_frame(frame)

    def accepts_timeout(self, starts: int, frames: int) -> bool:
        return self.accepts_quiet and starts == 0 and frames == 0

    def observe(self, service, request, completed, failed) -> None:
        if not self.observes:
            raise ValueError("Immediate snapshots do not require observation.")
        self._observe(service, request, completed, failed)

    def request_capture(self, service, request, completed, failed) -> None:
        self._observe(service, request, completed, failed)

    def validate_observation(self, observation: WindowVisualObservation | None) -> None:
        if observation is None:
            if self.observes:
                raise ValueError("Observed capture has no frame-condition receipt.")
            return
        if observation.condition is not self:
            raise ValueError("Frame-condition receipt does not match the capture contract.")
        self._validate(observation)


@dataclass(frozen=True, slots=True)
class WindowRenderFrame:
    """Native renderer completion witnessed after this observation was armed."""

    window_identity: int
    renderer_identity: int
    completed_at_monotonic: float


class WindowSnapshotRenderOwner(ABC):
    """Native completion/request hooks; never a replacement painter or loop."""

    @property
    @abstractmethod
    def widget(self) -> QWidget:
        """Qt widget owning the renderer and the observation's lifetime."""

    @property
    @abstractmethod
    def frame_completed(self) -> pyqtBoundSignal:
        """Signal emitted by the renderer only after completing a native frame."""

    @abstractmethod
    def request_frame(self) -> None:
        """Ask the existing renderer to produce a new frame."""


@dataclass(frozen=True)
class OpenGLWidgetSnapshotRenderOwner(WindowSnapshotRenderOwner):
    """Qt's native swap receipt, including Vispy's QOpenGLWidget backend."""

    canvas: QOpenGLWidget

    @property
    def widget(self) -> QWidget:
        return self.canvas

    @property
    def frame_completed(self) -> pyqtBoundSignal:
        return self.canvas.frameSwapped

    def request_frame(self) -> None:
        self.canvas.update()


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
    render_frame: WindowRenderFrame | None = None
    observation_budget_s: float | None = None
    operation_deadline: OperationDeadline | None = None


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

    def snapshot_operation_deadline(self) -> OperationDeadline | None:
        """Optional enclosing operation supplied by a product request owner."""
        return None

    @staticmethod
    def observation_phase_budget(remaining_seconds: float) -> float:
        """Reserve the other half of an operation for capture/reply delivery."""
        return remaining_seconds / 2

    def same_capture_contract(self, other: WindowSnapshotCaptureSpec) -> bool:
        """Return whether two snapshot carriers request the same capture."""

        return project_dataclass(WindowSnapshotCaptureSpec, self) == project_dataclass(
            WindowSnapshotCaptureSpec, other
        )

    def capture_fields(self) -> dict[str, object]:
        """Project every capture-owned field, excluding independent carrier fields."""
        return {
            declared.name: getattr(self, declared.name)
            for declared in fields(WindowSnapshotCaptureSpec)
        }


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
    render_owner: WindowSnapshotRenderOwner | None = None
    operation_deadline: OperationDeadline | None = None

    def observation_budget_seconds(self) -> float:
        """Allocate observation/reply phases from the one remaining deadline.

        Equal phase allocation is a budget policy, not a renderer settling time.
        Queue time is already consumed; the original timer is the only engine.
        """
        if self.operation_deadline is None:
            return self.capture.observation_timeout_s
        return min(
            self.capture.observation_timeout_s,
            self.capture.observation_phase_budget(self.operation_deadline.remaining_seconds()),
        )

    def require_operation_budget(self) -> None:
        if self.operation_deadline is not None:
            self.operation_deadline.remaining_seconds()


class QtWindowSnapshotService:
    """Capture Qt-rendered widget/window pixels to bounded file artifacts."""

    MIME_TYPE = "image/png"
    FILE_EXTENSION = ".png"
    SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")

    def request_capture(
        self,
        request: QtWindowSnapshotRequest,
        completed: Callable[[QtWindowSnapshot], None],
        failed: Callable[[WindowSnapshotObservationFailure], None],
    ) -> None:
        """Capture through the requested condition's declared implementation."""
        request.capture.frame_condition.request_capture(self, request, completed, failed)

    def observe(
        self,
        request: QtWindowSnapshotRequest,
        completed: Callable[[QtWindowSnapshot], None],
        failed: Callable[[WindowSnapshotObservationFailure], None],
    ) -> None:
        """Arm a bounded real-renderer observation without blocking UI mutations."""
        request.capture.frame_condition.observe(self, request, completed, failed)

    def capture(
        self,
        request: QtWindowSnapshotRequest,
        observation: WindowVisualObservation | None = None,
    ) -> QtWindowSnapshot:
        """Render and persist one screenshot from the requested Qt owner."""

        request.capture.frame_condition.validate_observation(observation)
        request.require_operation_budget()
        pixmap = request.capture.capture_scope.capture(request.widget)
        return self._persist(request, pixmap, observation)

    def _persist(
        self,
        request: QtWindowSnapshotRequest,
        pixmap: QPixmap,
        observation: WindowVisualObservation | None = None,
    ) -> QtWindowSnapshot:
        """Persist the same native render whose receipt was observed."""
        request.capture.frame_condition.validate_observation(observation)
        request.require_operation_budget()
        if pixmap.isNull():
            raise RuntimeError(
                f"Qt screenshot capture returned an empty pixmap for {request.subject_id!r}."
            )

        output_dir = Path(request.capture.output_dir_path).expanduser().resolve(strict=False)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / self._filename(request)
        from PyQt6.QtCore import QIODevice, QSaveFile

        output = QSaveFile(str(output_path))
        if not output.open(QIODevice.OpenModeFlag.WriteOnly):
            raise RuntimeError(f"Failed to open Qt screenshot {output_path}.")
        try:
            if not pixmap.save(output, "PNG"):
                raise RuntimeError(f"Failed to save Qt screenshot to {output_path}.")
            request.require_operation_budget()
            if not output.commit():
                raise RuntimeError(f"Failed to commit Qt screenshot {output_path}.")
        except Exception:
            output.cancelWriting()
            raise
        try:
            image_bytes = output_path.read_bytes()
            digest = hashlib.sha256(image_bytes).hexdigest()
            request.require_operation_budget()
        except Exception:
            # Only the unique artifact just created by this operation is removed.
            output_path.unlink(missing_ok=True)
            raise
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


class _WindowSnapshotObservation(ABC):
    """One Qt-owned deadline, capture, failure and cleanup algorithm."""

    def __init__(self, service, request, completed, failed, owner, flash_duration_s=0.0):
        from PyQt6.QtCore import QTimer, Qt

        self.service, self.request = service, request
        self.completed, self.failed = completed, failed
        self.condition = request.capture.frame_condition
        self.started = time.perf_counter()
        self.window_identity = id(request.widget.window())
        self.starts = self.frames = 0
        self.closed = False
        self.last_painted_frame = None
        self.render_frame = None
        self.flash_duration_s = flash_duration_s
        self.connections = []
        self.timer = QTimer(owner)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setSingleShot(True)
        # The Qt-owned timer retains this bounded observation, not a registry.
        self._connect(self.timer.timeout, lambda: self._timeout())
        self._connect(owner.destroyed, self._destroyed)
        self.observation_budget_s = 0.0
        try:
            self.observation_budget_s = request.observation_budget_seconds()
        except TimeoutError as error:
            self._fail(error)
        else:
            self.timer.start(int(self.observation_budget_s * 1000 + 0.999))

    def _connect(self, signal, callback):
        signal.connect(callback)
        self.connections.append((signal, callback))

    def _receipt(self, frame=None, *, failure=False):
        return WindowVisualObservation(
            condition=self.condition,
            window_identity=self.window_identity,
            started_at_monotonic=self.started,
            completed_at_monotonic=time.perf_counter(),
            configured_flash_duration_s=self.flash_duration_s,
            baseline_inactive=True,
            flash_start_count=self.starts,
            painted_frame_count=self.frames,
            frame=self.last_painted_frame if failure else frame,
            trace=FlashTrace.recent() if failure else (),
            render_frame=self.render_frame,
            observation_budget_s=self.observation_budget_s,
            operation_deadline=self.request.operation_deadline,
        )

    def _timeout(self):
        if self.condition.accepts_timeout(self.starts, self.frames):
            self._finish()
        else:
            self._fail(
                TimeoutError(
                    f"Requested {self.condition.value} was not observed; "
                    f"target flash starts={self.starts}, painted frames={self.frames}."
                )
            )

    def _fail(self, error):
        if self.closed:
            return
        receipt = self._receipt(failure=True)
        self._close()
        self.failed(WindowSnapshotObservationFailure(error, receipt))

    def _finish(self, frame=None, pixmap=None):
        if self.closed:
            return
        # A blocked Qt thread can deliver a renderer signal before its queued
        # timeout event. The original deadline still bounds admission.
        if (
            time.perf_counter() - self.started >= self.observation_budget_s
            and not self.condition.accepts_timeout(self.starts, self.frames)
        ):
            self._timeout()
            return
        receipt = self._receipt(frame)
        self._close()
        try:
            snapshot = (
                self.service.capture(self.request, receipt)
                if pixmap is None
                else self.service._persist(self.request, pixmap, receipt)
            )
        except Exception as exc:
            self.failed(WindowSnapshotObservationFailure(exc, receipt))
        else:
            self.completed(snapshot)

    def _close(self, *, destroyed=False):
        if self.closed:
            return
        self.closed = True
        if not destroyed:
            self.timer.stop()
            for signal, callback in self.connections:
                signal.disconnect(callback)
            self.timer.deleteLater()
        else:
            # Foreign-owner signals (the shared flash coordinator) also need
            # releasing. Qt may already have deleted owner/child signals.
            for signal, callback in self.connections:
                try:
                    signal.disconnect(callback)
                except (RuntimeError, TypeError):
                    pass
        self.connections.clear()

    def _destroyed(self):
        if self.closed:
            return
        receipt = self._receipt(failure=True)
        self._close(destroyed=True)
        self.failed(
            WindowSnapshotObservationFailure(
                RuntimeError("Observed window was destroyed before capture."),
                receipt,
            )
        )


class _WindowRenderSnapshotObservation(_WindowSnapshotObservation):
    """Small native-render hooks on the shared observation lifecycle."""

    def __init__(self, service, request, completed, failed):
        owner = request.render_owner
        if owner is None:
            raise ValueError("Render-complete snapshots require a native render owner.")
        if owner.widget.window() is not request.widget.window():
            raise ValueError("Render owner belongs to a different snapshot window.")
        self.renderer_identity = id(owner.widget)
        super().__init__(service, request, completed, failed, owner.widget)
        if self.closed:
            return
        self._connect(owner.frame_completed, self._render_completed)
        try:
            owner.request_frame()
        except Exception as exc:
            self._fail(exc)

    def _render_completed(self):
        if self.closed:
            return
        self.frames += 1
        self.render_frame = WindowRenderFrame(
            self.window_identity,
            self.renderer_identity,
            time.perf_counter(),
        )
        self._finish()


class _WindowFlashSnapshotObservation(_WindowSnapshotObservation):
    """Flash-owner hooks on the shared observation lifecycle."""

    def __init__(self, service, request, completed, failed):
        from pyqt_reactive.animation.flash_mixin import WindowFlashOverlay

        self.overlay = WindowFlashOverlay.get_for_window(request.widget)
        if not isinstance(self.overlay, WindowFlashOverlay):
            raise ValueError("This window has no supported flash-painter observation owner.")
        self.config = self.overlay.flash_observation_config()
        if request.capture.observation_timeout_s < self.config.total_duration_s:
            raise ValueError("Observation timeout must cover the configured flash interval.")
        if self.overlay.has_pending_or_active_flash():
            raise ValueError("Flash observation requires an inactive target-window baseline.")
        super().__init__(
            service, request, completed, failed, self.overlay, self.config.total_duration_s
        )
        if self.closed:
            return
        self.rendering = False
        self.rendered_frame = None
        self.start_signal = self.overlay.flash_start_signal()
        self._connect(self.start_signal, self._started)
        self._connect(self.overlay.frame_painted, self._painted)
        if self.condition.requests_native_render:
            self._connect(self.overlay.native_render_requested, self._render_current_frame)

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
            self._fail(exc)
            return
        finally:
            self.rendering = False
        if self.rendered_frame is not None:
            self._finish(self.rendered_frame, pixmap)
