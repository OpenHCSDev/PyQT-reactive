from __future__ import annotations

import subprocess
import sys
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
