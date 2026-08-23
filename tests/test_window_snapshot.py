from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtWidgets import QLabel, QWidget

from pyqt_reactive.services.window_snapshot import (
    QtWindowSnapshotRequest,
    QtWindowSnapshotService,
    WindowSnapshotCaptureScope,
    WindowSnapshotCaptureSpec,
)


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
