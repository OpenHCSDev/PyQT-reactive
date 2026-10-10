from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass, fields, replace
import time

import pytest
from PyQt6.QtWidgets import QLabel, QWidget

from pyqt_reactive.services.window_snapshot import (
    QtWindowSnapshotRequest,
    QtWindowSnapshotService,
    WindowSnapshotCaptureScope,
    WindowSnapshotCaptureSpec,
    WindowSnapshotFrameCondition,
    WindowSnapshotRenderOwner,
)


@pytest.fixture
def observed_form(qapp, qtbot):
    import objectstate.config as config_module
    from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QDialog, QVBoxLayout
    from pyqt_reactive.animation.flash_mixin import WindowFlashOverlay, _GlobalFlashCoordinator
    from pyqt_reactive.forms.parameter_form_manager import FormManagerConfig, ParameterFormManager
    from pyqt_reactive.theming import ColorScheme

    @dataclass
    class Fields:
        number: int = 3
        maybe: int | None = None

    previous_base = config_module._base_config_type
    ObjectStateRegistry.clear()
    set_base_config_type(Fields)

    class CapturedDialog(QDialog):
        def __init__(self):
            super().__init__()
            self.grab_depth = 0
            self.maximum_grab_depth = 0
            self.native_grab_count = 0

        def grab(self, *args):
            self.grab_depth += 1
            self.maximum_grab_depth = max(self.maximum_grab_depth, self.grab_depth)
            self.native_grab_count += 1
            try:
                return super().grab(*args)
            finally:
                self.grab_depth -= 1

    window = CapturedDialog()
    window.resize(420, 180)
    form = ParameterFormManager(
        ObjectState(Fields()),
        FormManagerConfig(
            color_scheme=ColorScheme(),
            use_scroll_area=False,
        ),
    )
    QVBoxLayout(window).addWidget(form)
    with qtbot.waitExposed(window):
        window.show()
    yield window, form
    coordinator = _GlobalFlashCoordinator.get()
    if coordinator._timer is not None:
        coordinator._timer.stop()
    coordinator._computed_colors.clear()
    coordinator._playbacks.clear()
    coordinator._pending_flash_keys.clear()
    coordinator._active_windows.clear()
    from PyQt6 import sip

    if not sip.isdeleted(window):
        WindowFlashOverlay.cleanup_window(window)
        window.close()
        window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    ObjectStateRegistry.clear()
    config_module._base_config_type = previous_base


def _observation_request(window, tmp_path, condition):
    return QtWindowSnapshotRequest(
        widget=window,
        subject_id="observed-form",
        title="Observed Form",
        capture=WindowSnapshotCaptureSpec(
            output_dir_path=str(tmp_path),
            capture_scope=WindowSnapshotCaptureScope.WINDOW,
            frame_condition=condition,
            observation_timeout_s=1.0,
        ),
    )


@pytest.mark.parametrize(
    "field_name", tuple(field.name for field in fields(WindowSnapshotCaptureSpec))
)
def test_capture_comparison_derives_every_declared_owner_field(tmp_path, field_name):
    baseline = WindowSnapshotCaptureSpec(output_dir_path=str(tmp_path))
    changes = {
        "output_dir_path": str(tmp_path / "other"),
        "capture_scope": WindowSnapshotCaptureScope.WINDOW,
        "frame_condition": WindowSnapshotFrameCondition.NO_FLASH,
        "observation_timeout_s": 2.0,
    }
    assert baseline.same_capture_contract(replace(baseline))
    assert not baseline.same_capture_contract(
        replace(baseline, **{field_name: changes[field_name]})
    )


def test_capture_comparison_ignores_carrier_fields_outside_owner(tmp_path):
    @dataclass(frozen=True, kw_only=True)
    class SubjectCapture(WindowSnapshotCaptureSpec):
        subject: str

    left = SubjectCapture(output_dir_path=str(tmp_path), subject="left")
    right = SubjectCapture(output_dir_path=str(tmp_path), subject="right")
    assert left.same_capture_contract(right)


@pytest.fixture
def rendered_canvas(qapp, qtbot):
    """A real Qt painter and completion receipt, never a pixel/content mock."""
    from PyQt6.QtCore import QEvent, pyqtSignal
    from PyQt6.QtGui import QColor, QPainter

    class Canvas(QWidget):
        frame_completed = pyqtSignal()

        def __init__(self):
            super().__init__()
            self.color = QColor("black")
            self.paint_count = 0

        def paintEvent(self, event):
            painter = QPainter(self)
            painter.fillRect(self.rect(), self.color)
            painter.end()
            self.paint_count += 1
            self.frame_completed.emit()

    canvas = Canvas()
    canvas.resize(80, 60)
    # Native platforms expose a shown window asynchronously; Qt paints only
    # exposed windows.
    with qtbot.waitExposed(canvas):
        canvas.show()
    yield canvas
    from PyQt6 import sip

    if not sip.isdeleted(canvas):
        canvas.close()
        canvas.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


class PaintWidgetAccess:
    def __init__(self, canvas, **kwargs):
        self.canvas = canvas
        super().__init__(**kwargs)

    @property
    def widget(self):
        return self.canvas


class PaintCompletionCapability:
    @property
    def frame_completed(self):
        return self.widget.frame_completed


class PaintRequestCapability:
    def request_frame(self):
        self.widget.update()


class PaintRenderOwner(
    PaintWidgetAccess,
    PaintCompletionCapability,
    PaintRequestCapability,
    WindowSnapshotRenderOwner,
):
    """New case declared solely through independent native capabilities."""


def _drain_until(qapp, predicate):
    deadline = time.perf_counter() + 1.0
    while not predicate() and time.perf_counter() < deadline:
        qapp.processEvents()
    assert predicate()


def _render_request(canvas, tmp_path, owner=None, timeout=1.0):
    return replace(
        _observation_request(canvas, tmp_path, WindowSnapshotFrameCondition.RENDER_COMPLETE),
        render_owner=owner,
        capture=WindowSnapshotCaptureSpec(
            output_dir_path=str(tmp_path),
            frame_condition=WindowSnapshotFrameCondition.RENDER_COMPLETE,
            observation_timeout_s=timeout,
        ),
    )


def test_render_complete_waits_for_real_qt_paint_and_captures_once(
    qapp,
    rendered_canvas,
    tmp_path,
):
    from PyQt6.QtGui import QColor, QImage

    canvas = rendered_canvas
    completed, failed = [], []
    prior_paints = canvas.paint_count
    canvas.color = QColor("red")
    request = _render_request(canvas, tmp_path, PaintRenderOwner(canvas))
    QtWindowSnapshotService().request_capture(request, completed.append, failed.append)
    assert not completed and not failed
    _drain_until(qapp, lambda: bool(completed or failed))
    assert not failed and len(completed) == 1
    snapshot = completed[0]
    assert canvas.paint_count > prior_paints
    assert QImage(snapshot.path).pixelColor(30, 30) == QColor("red")
    receipt = snapshot.observation
    assert receipt.render_frame.window_identity == id(canvas.window())
    assert receipt.render_frame.renderer_identity == id(canvas)
    assert receipt.started_at_monotonic <= receipt.render_frame.completed_at_monotonic
    assert receipt.painted_frame_count == 1
    assert canvas.receivers(canvas.frame_completed) == 0
    canvas.color = QColor("blue")
    canvas.update()
    qapp.processEvents()
    assert len(completed) == 1 and not failed


def test_render_new_case_reuses_shared_algorithm_with_cooperative_mro(
    qapp,
    rendered_canvas,
    tmp_path,
):
    class CountRequests:
        def __init__(self, **kwargs):
            self.requests = 0
            super().__init__(**kwargs)

        def request_frame(self):
            self.requests += 1
            super().request_frame()

    class CountedPaintOwner(CountRequests, PaintRenderOwner):
        pass

    owner = CountedPaintOwner(canvas=rendered_canvas)
    completed, failed = [], []
    QtWindowSnapshotService().request_capture(
        _render_request(rendered_canvas, tmp_path, owner),
        completed.append,
        failed.append,
    )
    _drain_until(qapp, lambda: bool(completed or failed))
    assert owner.requests == 1 and len(completed) == 1 and not failed


def test_render_missing_owner_and_wrong_window_fail_without_artifact(
    qapp,
    rendered_canvas,
    tmp_path,
):
    service = QtWindowSnapshotService()
    with pytest.raises(ValueError, match="native render owner"):
        service.request_capture(
            _render_request(rendered_canvas, tmp_path), lambda _: None, lambda _: None
        )
    other = QWidget()
    try:
        with pytest.raises(ValueError, match="different snapshot window"):
            service.request_capture(
                _render_request(rendered_canvas, tmp_path, PaintRenderOwner(other)),
                lambda _: None,
                lambda _: None,
            )
    finally:
        other.close()
    assert not tuple(tmp_path.glob("*.png"))


def test_render_timeout_never_captures_and_releases_native_signal(
    qapp,
    rendered_canvas,
    tmp_path,
):
    class StalledOwner(PaintRenderOwner):
        def request_frame(self):
            pass

    completed, failed = [], []
    QtWindowSnapshotService().request_capture(
        _render_request(rendered_canvas, tmp_path, StalledOwner(rendered_canvas), timeout=0.01),
        completed.append,
        failed.append,
    )
    _drain_until(qapp, lambda: bool(failed))
    assert not completed and len(failed) == 1
    assert isinstance(failed[0].error, TimeoutError)
    assert failed[0].observation.render_frame is None
    assert failed[0].observation.painted_frame_count == 0
    assert not tuple(tmp_path.glob("*.png"))
    assert rendered_canvas.receivers(rendered_canvas.frame_completed) == 0


def test_render_completion_after_deadline_cannot_overtake_queued_timeout(
    qapp,
    rendered_canvas,
    tmp_path,
    monkeypatch,
):
    import pyqt_reactive.services.window_snapshot as snapshot_module

    completed, failed = [], []
    now = [time.perf_counter()]
    with monkeypatch.context() as clock:
        clock.setattr(snapshot_module.time, "perf_counter", lambda: now[0])
        QtWindowSnapshotService().request_capture(
            _render_request(
                rendered_canvas, tmp_path, PaintRenderOwner(rendered_canvas), timeout=0.5
            ),
            completed.append,
            failed.append,
        )
        now[0] += 0.6
        qapp.processEvents()  # Real Qt paint, before the real timer has elapsed.
    assert not completed and len(failed) == 1
    assert isinstance(failed[0].error, TimeoutError)
    assert failed[0].observation.render_frame is not None
    assert not tuple(tmp_path.glob("*.png"))
    assert rendered_canvas.receivers(rendered_canvas.frame_completed) == 0


def test_render_owner_destroyed_fails_once_without_capture(
    qapp,
    rendered_canvas,
    tmp_path,
):
    from PyQt6.QtCore import QEvent

    completed, failed = [], []
    QtWindowSnapshotService().request_capture(
        _render_request(rendered_canvas, tmp_path, PaintRenderOwner(rendered_canvas)),
        completed.append,
        failed.append,
    )
    rendered_canvas.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _drain_until(qapp, lambda: bool(failed))
    assert not completed and len(failed) == 1
    assert isinstance(failed[0].error, RuntimeError)
    assert not tuple(tmp_path.glob("*.png"))


def test_operation_deadline_consumes_queue_time_and_preserves_failure(
    qapp, rendered_canvas, tmp_path
):
    from zmqruntime.timeouts import OperationDeadline

    completed, failed = [], []
    request = replace(
        _render_request(rendered_canvas, tmp_path, PaintRenderOwner(rendered_canvas)),
        operation_deadline=OperationDeadline("expired queued snapshot", 100, time.monotonic() - 1),
    )
    QtWindowSnapshotService().request_capture(request, completed.append, failed.append)
    assert not completed and len(failed) == 1
    assert isinstance(failed[0].error, TimeoutError)
    assert failed[0].observation.operation_deadline is request.operation_deadline
    assert failed[0].observation.observation_budget_s == 0
    assert not tuple(tmp_path.glob("*.png"))
    qapp.processEvents()
    assert len(failed) == 1 and not completed


def test_operation_deadline_cancels_late_real_png_commit(
    qapp, rendered_canvas, tmp_path, monkeypatch
):
    from PyQt6.QtCore import QSaveFile
    from zmqruntime.timeouts import OperationDeadline

    now = [time.monotonic()]
    completed, failed = [], []
    original_commit = QSaveFile.commit

    def commit(output):
        result = original_commit(output)
        now[0] += 2
        return result

    with monkeypatch.context() as clock:
        clock.setattr(time, "monotonic", lambda: now[0])
        clock.setattr(QSaveFile, "commit", commit)
        request = replace(
            _render_request(rendered_canvas, tmp_path, PaintRenderOwner(rendered_canvas)),
            operation_deadline=OperationDeadline.after_milliseconds(
                1000, operation="source capture"
            ),
        )
        QtWindowSnapshotService().request_capture(request, completed.append, failed.append)
        qapp.processEvents()
    assert not completed and len(failed) == 1
    assert isinstance(failed[0].error, TimeoutError)
    assert failed[0].observation.render_frame is not None
    assert not tuple(tmp_path.glob("*.png"))
    qapp.processEvents()
    assert len(failed) == 1 and not completed


def test_render_condition_cannot_be_silently_captured_immediately(rendered_canvas, tmp_path):
    with pytest.raises(ValueError, match="no frame-condition receipt"):
        QtWindowSnapshotService().capture(_render_request(rendered_canvas, tmp_path))


def test_shared_observer_preserves_actual_flash_painter_capture(qapp, observed_form, tmp_path):
    window, form = observed_form
    completed, failed = [], []
    QtWindowSnapshotService().request_capture(
        _observation_request(
            window,
            tmp_path,
            WindowSnapshotFrameCondition.FLASH_MAXIMUM_ALPHA,
        ),
        completed.append,
        failed.append,
    )
    form.update_parameter("number", 8)
    _drain_until(qapp, lambda: bool(completed or failed))
    assert len(completed) == 1 and not failed
    assert completed[0].observation.frame.has_maximum_alpha
    assert completed[0].observation.render_frame is None
    assert window.maximum_grab_depth == 1


def test_capture_follows_actual_maximum_alpha_paint_without_recursion(
    qtbot,
    observed_form,
    tmp_path,
):
    from PyQt6.QtGui import QImage

    window, form = observed_form
    completed, failed = [], []
    QtWindowSnapshotService().observe(
        _observation_request(
            window,
            tmp_path,
            WindowSnapshotFrameCondition.FLASH_MAXIMUM_ALPHA,
        ),
        completed.append,
        failed.append,
    )
    form.update_parameter("number", 8)
    qtbot.waitUntil(lambda: bool(completed or failed), timeout=2000)
    assert not failed
    assert len(completed) == 1
    snapshot = completed[0]
    receipt = snapshot.observation
    assert receipt.baseline_inactive
    assert receipt.flash_start_count > 0
    assert receipt.painted_frame_count > 0
    assert receipt.frame.window_identity == id(window)
    assert receipt.frame.has_maximum_alpha
    assert receipt.frame.configured_maximum_alpha == 255
    assert receipt.frame.configured_flash_duration_s == pytest.approx(0.85)
    assert window.native_grab_count > 0
    assert window.maximum_grab_depth == 1
    image = QImage(snapshot.path)
    full_color = next(
        element.rgba[:3] for element in receipt.frame.elements if element.rgba[3] == 255
    )
    assert any(
        image.pixelColor(x, y).getRgb()[:3] == full_color
        for y in range(image.height())
        for x in range(image.width())
    )
    qtbot.wait(20)
    assert len(completed) == 1, "Nested grab paint must not recapture the same request"


def test_armed_native_render_captures_actual_occluded_window(qtbot, observed_form, tmp_path):
    from PyQt6.QtWidgets import QWidget

    window, form = observed_form
    cover = QWidget()
    cover.resize(window.size())
    qtbot.addWidget(cover)
    cover.show()
    cover.raise_()
    completed, failed = [], []
    QtWindowSnapshotService().observe(
        _observation_request(
            window,
            tmp_path,
            WindowSnapshotFrameCondition.FLASH_MAXIMUM_ALPHA,
        ),
        completed.append,
        failed.append,
    )
    form.update_parameter("number", 8)
    qtbot.waitUntil(lambda: bool(completed or failed), timeout=2000)
    assert not failed
    assert completed[0].observation.frame.has_maximum_alpha
    assert window.maximum_grab_depth == 1


@pytest.mark.parametrize("field_name", ("number", "maybe"))
def test_noop_reset_is_observed_across_the_full_actual_flash_interval(
    qtbot,
    observed_form,
    tmp_path,
    field_name,
):
    window, form = observed_form
    completed, failed = [], []
    QtWindowSnapshotService().observe(
        _observation_request(
            window,
            tmp_path,
            WindowSnapshotFrameCondition.NO_FLASH,
        ),
        completed.append,
        failed.append,
    )
    form.reset_buttons[field_name].click()
    qtbot.waitUntil(lambda: bool(completed or failed), timeout=2000)
    assert not failed
    observation = completed[0].observation
    assert observation.baseline_inactive
    assert observation.flash_start_count == observation.painted_frame_count == 0
    assert (
        observation.completed_at_monotonic - observation.started_at_monotonic
        >= observation.configured_flash_duration_s
    )


def test_no_flash_observation_rejects_a_real_changed_value(qtbot, observed_form, tmp_path):
    window, form = observed_form
    completed, failed = [], []
    QtWindowSnapshotService().observe(
        _observation_request(
            window,
            tmp_path,
            WindowSnapshotFrameCondition.NO_FLASH,
        ),
        completed.append,
        failed.append,
    )
    form.update_parameter("number", 8)
    qtbot.waitUntil(lambda: bool(completed or failed), timeout=2000)
    assert not completed
    assert len(failed) == 1
    assert isinstance(failed[0].error, TimeoutError)
    assert "painted frames=" in str(failed[0].error)
    assert failed[0].observation.flash_start_count > 0
    assert failed[0].observation.painted_frame_count > 0


def test_observation_rejects_pending_flash_baseline(qapp, observed_form, tmp_path):
    window, form = observed_form
    form.update_parameter("number", 8)
    qapp.processEvents()
    with pytest.raises(ValueError, match="inactive target-window baseline"):
        QtWindowSnapshotService().observe(
            _observation_request(
                window,
                tmp_path,
                WindowSnapshotFrameCondition.NO_FLASH,
            ),
            lambda result: None,
            lambda error: None,
        )


def test_observation_rejects_a_bound_shorter_than_its_real_configuration(observed_form, tmp_path):
    window, form = observed_form
    request = QtWindowSnapshotRequest(
        widget=window,
        subject_id="short-bound",
        title="Short bound",
        capture=WindowSnapshotCaptureSpec(
            output_dir_path=str(tmp_path),
            frame_condition=WindowSnapshotFrameCondition.NO_FLASH,
            observation_timeout_s=0.1,
        ),
    )
    with pytest.raises(ValueError, match="configured flash interval"):
        QtWindowSnapshotService().observe(request, lambda result: None, lambda error: None)


def test_maximum_alpha_timeout_preserves_zero_activity_receipt(qtbot, observed_form, tmp_path):
    window, form = observed_form
    completed, failed = [], []
    QtWindowSnapshotService().observe(
        _observation_request(
            window,
            tmp_path,
            WindowSnapshotFrameCondition.FLASH_MAXIMUM_ALPHA,
        ),
        completed.append,
        failed.append,
    )
    qtbot.waitUntil(lambda: bool(completed or failed), timeout=2000)
    assert not completed
    assert isinstance(failed[0].error, TimeoutError)
    receipt = failed[0].observation
    assert receipt.baseline_inactive
    assert receipt.flash_start_count == receipt.painted_frame_count == 0
    assert receipt.frame is None


def test_nonmaximum_native_paint_is_preserved_only_as_failure_diagnostics(
    qtbot,
    observed_form,
    tmp_path,
    monkeypatch,
):
    from pyqt_reactive.animation.flash_mixin import WindowFlashOverlay, _GlobalFlashCoordinator
    from pyqt_reactive.flash_trace import FlashTrace, FlashTraceRecord

    window, form = observed_form
    overlay = WindowFlashOverlay.get_for_window(window)
    coordinator = _GlobalFlashCoordinator.get()
    monkeypatch.setattr(coordinator, "_config", replace(coordinator._config, fade_in_s=5.0))
    painted, completed, failed = [], [], []

    def stop_after_actual_paint(frame):
        painted.append(frame)
        coordinator._timer.stop()
        coordinator._playbacks.clear()
        coordinator._computed_colors.clear()

    overlay.frame_painted.connect(stop_after_actual_paint)
    try:
        request = _observation_request(
            window, tmp_path, WindowSnapshotFrameCondition.FLASH_MAXIMUM_ALPHA
        )
        request = replace(request, capture=replace(request.capture, observation_timeout_s=6.0))
        QtWindowSnapshotService().observe(request, completed.append, failed.append)
        form.update_parameter("number", 8)
        qtbot.waitUntil(lambda: bool(completed or failed), timeout=7000)
        assert painted and all(not frame.has_maximum_alpha for frame in painted)
        assert not completed
        assert len(failed) == 1
        assert isinstance(failed[0].error, TimeoutError)
        receipt = failed[0].observation
        assert receipt.frame is painted[-1]
        assert receipt.frame.window_identity == id(window)
        assert not receipt.frame.has_maximum_alpha
        assert receipt.painted_frame_count == len(painted)
        assert receipt.trace == FlashTrace.recent()
        assert receipt.trace and len(receipt.trace) <= 300
        assert all(isinstance(record, FlashTraceRecord) for record in receipt.trace)
        assert not tuple(
            tmp_path.glob("*.png")
        ), "A nonmaximum frame must never yield a captured PNG"
    finally:
        overlay.frame_painted.disconnect(stop_after_actual_paint)


def test_legacy_trace_import_preserves_the_canonical_declaration_and_ring():
    from pyqt_reactive import flash_trace as canonical
    from pyqt_reactive.animation import flash_trace as legacy

    assert legacy.FlashTrace is canonical.FlashTrace
    assert legacy.FlashTraceRecord is canonical.FlashTraceRecord
    assert legacy.flash_trace is canonical.flash_trace
    assert legacy.logger is canonical.logger


def test_native_stalled_render_presents_the_declared_maximum_without_duration_override(
    qtbot,
    observed_form,
    tmp_path,
    monkeypatch,
):
    import time
    from pyqt_reactive.animation.flash_mixin import WindowFlashOverlay, _GlobalFlashCoordinator

    window, form = observed_form
    overlay = WindowFlashOverlay.get_for_window(window)
    coordinator = _GlobalFlashCoordinator.get()
    original = overlay._ensure_geometry_cache_for_keys
    stalled = []

    def expensive_visible_geometry(keys):
        original(keys)
        if coordinator._playbacks and not stalled:
            stalled.append(time.perf_counter())
            time.sleep(0.35)  # Native regression: real GUI-thread work skips the old wall plateau.

    monkeypatch.setattr(overlay, "_ensure_geometry_cache_for_keys", expensive_visible_geometry)
    completed, failed = [], []
    started = time.perf_counter()
    QtWindowSnapshotService().observe(
        _observation_request(
            window,
            tmp_path,
            WindowSnapshotFrameCondition.FLASH_MAXIMUM_ALPHA,
        ),
        completed.append,
        failed.append,
    )
    form.update_parameter("number", 8)
    qtbot.waitUntil(lambda: bool(completed or failed), timeout=2000)
    assert stalled and time.perf_counter() - started >= 0.35
    assert not failed and len(completed) == 1
    frame = completed[0].observation.frame
    assert frame.has_maximum_alpha
    assert frame.configured_flash_duration_s == pytest.approx(0.85)
    assert coordinator._config.fade_in_s == 0.2
    assert coordinator._config.hold_s == 0.05
    assert coordinator._config.fade_out_s == 0.6
    assert window.maximum_grab_depth == 1


def test_two_actual_windows_both_present_maximum_before_shared_hold(
    qtbot,
    observed_form,
    tmp_path,
    flash_clock,
):
    from PyQt6.QtWidgets import QDialog, QVBoxLayout
    from pyqt_reactive.animation.flash_config import FlashPhase
    from pyqt_reactive.animation.flash_mixin import WindowFlashOverlay, _GlobalFlashCoordinator
    from pyqt_reactive.forms.parameter_form_manager import FormManagerConfig, ParameterFormManager
    from pyqt_reactive.theming import ColorScheme

    first, form = observed_form
    second = QDialog()
    qtbot.addWidget(second)
    second.resize(first.size())
    second_form = ParameterFormManager(
        form.state,
        FormManagerConfig(
            color_scheme=ColorScheme(),
            use_scroll_area=False,
        ),
    )
    QVBoxLayout(second).addWidget(second_form)
    with qtbot.waitExposed(second):
        second.show()
    coordinator = _GlobalFlashCoordinator.get()
    overlay = WindowFlashOverlay.get_for_window(first)
    phases_after_first_maximum = []

    def actual_first_paint(frame):
        if frame.has_maximum_alpha:
            phases_after_first_maximum.append(coordinator._playbacks["number"].phase)

    overlay.frame_painted.connect(actual_first_paint)
    completed, failed = [], []
    try:
        service = QtWindowSnapshotService()
        for window in (first, second):
            service.observe(
                _observation_request(
                    window, tmp_path, WindowSnapshotFrameCondition.FLASH_MAXIMUM_ALPHA
                ),
                completed.append,
                failed.append,
            )
        form.update_parameter("number", 8)
        qtbot.waitUntil(lambda: "number" in coordinator._playbacks, timeout=2000)
        flash_clock.advance(coordinator._config.fade_in_s)
        qtbot.waitUntil(lambda: len(completed) == 2 or bool(failed), timeout=2000)
        assert not failed and len(completed) == 2
        assert {result.observation.frame.window_identity for result in completed} == {
            id(first),
            id(second),
        }
        assert all(result.observation.frame.has_maximum_alpha for result in completed)
        assert phases_after_first_maximum[0] is FlashPhase.FADE_IN
        assert coordinator._playbacks["number"].phase is FlashPhase.HOLD
    finally:
        overlay.frame_painted.disconnect(actual_first_paint)
        WindowFlashOverlay.cleanup_window(second)
        second.close()


def test_observation_destruction_fails_once_with_stable_window_identity(
    qapp,
    qtbot,
    observed_form,
    tmp_path,
):
    from PyQt6.QtCore import QEvent

    window, form = observed_form
    completed, failed = [], []
    identity = id(window)
    QtWindowSnapshotService().observe(
        _observation_request(
            window,
            tmp_path,
            WindowSnapshotFrameCondition.NO_FLASH,
        ),
        completed.append,
        failed.append,
    )
    window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qtbot.waitUntil(lambda: bool(failed), timeout=1000)
    assert not completed
    assert len(failed) == 1
    assert failed[0].observation.window_identity == identity


@pytest.mark.parametrize("timeout", (0, -1, float("nan"), float("inf"), 31))
def test_observation_timeout_is_finite_and_bounded(tmp_path, timeout):
    with pytest.raises(ValueError, match="observation_timeout_s"):
        WindowSnapshotCaptureSpec(output_dir_path=str(tmp_path), observation_timeout_s=timeout)


@pytest.mark.parametrize(
    ("capture_scope", "expected_size"),
    (
        (WindowSnapshotCaptureScope.WIDGET, (240, 80)),
        (WindowSnapshotCaptureScope.WINDOW, (320, 160)),
    ),
)
def test_window_snapshot_renders_only_declared_qt_owners(
    qtbot,
    tmp_path: Path,
    capture_scope: WindowSnapshotCaptureScope,
    expected_size: tuple[int, int],
) -> None:
    window = QWidget()
    window.resize(*expected_size)
    label = QLabel("OpenHCS snapshot", parent=window)
    label.resize(240, 80)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    snapshot = QtWindowSnapshotService().capture(
        QtWindowSnapshotRequest(
            widget=label,
            capture=WindowSnapshotCaptureSpec(
                output_dir_path=str(tmp_path),
                capture_scope=capture_scope,
            ),
            subject_id="test-window",
            title="Test Window",
        )
    )

    assert snapshot.mime_type == "image/png"
    assert (snapshot.width, snapshot.height) == expected_size
    assert snapshot.size_bytes > 0
    assert snapshot.sha256
    assert snapshot.path.endswith(".png")
    assert Path(snapshot.path).is_file()


def test_native_desktop_pixel_capture_is_not_a_declared_scope() -> None:
    assert tuple(WindowSnapshotCaptureScope) == (
        WindowSnapshotCaptureScope.WIDGET,
        WindowSnapshotCaptureScope.WINDOW,
    )
    with pytest.raises(ValueError, match="'native' is not a valid"):
        WindowSnapshotCaptureScope("native")


def test_window_snapshot_declarations_are_headless_importable() -> None:
    script = """
import builtins
import sys

original_import = builtins.__import__

def reject_pyqt(name, globals=None, locals=None, fromlist=(), level=0):
    if name == 'PyQt6' or name.startswith('PyQt6.'):
        raise AssertionError(f'window snapshot declarations imported {name}')
    return original_import(name, globals, locals, fromlist, level)

builtins.__import__ = reject_pyqt
from pyqt_reactive.services.window_snapshot import WindowSnapshotCaptureScope
assert tuple(scope.value for scope in WindowSnapshotCaptureScope) == ('widget', 'window')
assert not any(name == 'PyQt6' or name.startswith('PyQt6.') for name in sys.modules)
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
