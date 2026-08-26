"""Qt value declarations remain importable without loading the GUI runtime."""

from __future__ import annotations

import subprocess
import sys


def test_qt_type_declarations_do_not_import_pyqt6() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from pyqt_reactive.qt_types import QtColorText, QtKeySequenceText; "
                "assert QtColorText is not None; "
                "assert QtKeySequenceText is not None; "
                "assert not any(name == 'PyQt6' or name.startswith('PyQt6.') "
                "for name in sys.modules)"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
