"""Original Vispy native Qt widget contract, no GL paint or product startup."""

import time

import pytest
from qtpy import API_NAME, QtCore, QtGui, QtWidgets
from vispy.app import Canvas

from pyqt_reactive.services.window_snapshot import (
    OpenGLWidgetSnapshotRenderOwner,
    QtWindowSnapshotRequest,
    QtWindowSnapshotService,
    WindowSnapshotCaptureSpec,
    WindowSnapshotFrameCondition,
)


class QtPySnapshotService(QtWindowSnapshotService):
    """A new integration needs only its existing binding declaration/hook."""

    @staticmethod
    def qt_core():
        return QtCore


@pytest.fixture
def vispy_native():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = QtWidgets.QLabel("Original Qt binding fixture")
    window.resize(160, 80)
    canvas = Canvas(parent=window, show=False, size=(64, 64))
    from vispy.app.backends._qt import CanvasBackendDesktop, QGLWidget

    native = canvas.native
    assert isinstance(native, CanvasBackendDesktop)
    assert isinstance(native, QGLWidget)
    assert isinstance(native, QtCore.QObject)
    assert native.frameSwapped is not None
    native.hide()
    print(f"QtPy binding={API_NAME}; native MRO={type(native).__mro__}")
    yield app, window, native
    canvas.close()
    window.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    app.processEvents()


def test_real_vispy_native_timer_and_typed_no_frame_receipt(vispy_native, tmp_path):
    app, window, native = vispy_native
    request = QtWindowSnapshotRequest(
        widget=window,
        capture=WindowSnapshotCaptureSpec(
            output_dir_path=str(tmp_path),
            frame_condition=WindowSnapshotFrameCondition.RENDER_COMPLETE,
            observation_timeout_s=0.02,
        ),
        subject_id="real_vispy",
        title="Real Vispy binding",
        render_owner=OpenGLWidgetSnapshotRenderOwner(native),
    )
    completed, failed = [], []
    QtPySnapshotService().request_capture(request, completed.append, failed.append)
    timer = native.findChild(QtCore.QTimer)
    assert timer is not None and timer.parent() is native
    end = time.monotonic() + 0.4
    while not failed and time.monotonic() < end:
        app.processEvents()
    assert not completed and len(failed) == 1
    assert "not observed" in str(failed[0])
    assert failed[0].observation.render_frame is None
    assert failed[0].observation.painted_frame_count == 0
    assert not tuple(tmp_path.glob("*.png"))
    native.frameSwapped.emit()  # Signal cleanup, not proof of a rendered GL frame.
    app.processEvents()
    assert not completed and len(failed) == 1 and not tuple(tmp_path.glob("*.png"))


def test_real_binding_pixmap_uses_same_atomic_persistence(vispy_native, tmp_path):
    _, window, _ = vispy_native
    request = QtWindowSnapshotRequest(
        widget=window,
        capture=WindowSnapshotCaptureSpec(output_dir_path=str(tmp_path)),
        subject_id="real_binding",
        title="Binding-owned PNG",
    )
    snapshot = QtPySnapshotService().capture(request)
    image = QtGui.QImage(snapshot.path)
    assert not image.isNull() and image.width() == 160 and image.height() == 80
    assert snapshot.capture.same_capture_contract(request.capture)


def test_new_binding_declaration_reuses_original_capture_and_observation():
    assert QtPySnapshotService.qt_core() is QtCore
    assert QtPySnapshotService.capture is QtWindowSnapshotService.capture
    assert QtPySnapshotService.observe is QtWindowSnapshotService.observe
