"""Preview declarations remain usable without loading the native UI runtime."""

import subprocess
import sys


def test_preview_configuration_import_does_not_load_qt():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import builtins
import sys

original_import = builtins.__import__

def reject_qt(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "PySide6" or name.startswith("PySide6."):
        raise AssertionError(f"Preview declaration imported {name}")
    return original_import(name, globals, locals, fromlist, level)

builtins.__import__ = reject_qt
from pyqt_reactive.strategies.preview_formatting import FormattingConfig

assert FormattingConfig() is not None
assert not any(name == "PySide6" or name.startswith("PySide6.") for name in sys.modules)
""",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
