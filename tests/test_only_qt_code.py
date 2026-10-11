"""pyqt-reactive holds only Qt code; toolkit-neutral modules live in formbridge."""

from __future__ import annotations

import ast
from pathlib import Path

from formbridge.services.window_snapshot import (
    FrameObservation,
    WindowSnapshotCaptureScope,
)

from pyqt_reactive.services.window_snapshot import QtCaptureScope, QtFrameObservation

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "pyqt_reactive"
QT_PACKAGES = frozenset({"PyQt6", "qtpy", "vispy", "magicgui", "pyqtgraph", "OpenGL"})


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(PACKAGE_ROOT.parent).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _imports(path: Path) -> set[str]:
    package = _module_name(path).split(".")
    if path.name != "__init__.py":
        package = package[:-1]
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            module = ".".join([*base, *([node.module] if node.module else [])])
            names.add(module)
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return names


def test_every_module_is_qt_code() -> None:
    """Each module imports a Qt binding, directly or through another package module."""

    every_module = {_module_name(path): path for path in PACKAGE_ROOT.rglob("*.py")}
    modules = {name: path for name, path in every_module.items() if path.name != "__init__.py"}
    imports = {name: _imports(path) for name, path in every_module.items()}
    qt = {name for name, names in imports.items() if {n.split(".")[0] for n in names} & QT_PACKAGES}
    grew = True
    while grew:
        grew = False
        for name, names in imports.items():
            if name not in qt and any(
                imported == other or imported.startswith(other + ".")
                for imported in names
                for other in qt
            ):
                qt.add(name)
                grew = True
    assert sorted(set(modules) - qt) == []


def test_every_capture_scope_and_frame_observation_has_a_qt_implementation() -> None:
    assert set(QtCaptureScope.__registry__) == set(WindowSnapshotCaptureScope)
    kinds = {kind for kind in FrameObservation.__subclasses__()}
    assert set(QtFrameObservation.__registry__) == kinds
