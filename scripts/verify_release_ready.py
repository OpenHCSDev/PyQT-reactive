#!/usr/bin/env python3
"""Verify pyqt-reactive source and distribution release invariants."""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INIT_PATH = PROJECT_ROOT / "src" / "pyqt_reactive" / "__init__.py"
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
README_PATH = PROJECT_ROOT / "README.md"
PUBLISH_WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "publish.yml"
DIST_PATH = PROJECT_ROOT / "dist"
BUILD_PATH = PROJECT_ROOT / "build"
SEMANTIC_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[a-zA-Z0-9.+-]*)?$")


def declared_version() -> str:
    """Return the package version from its hatchling authority."""
    module = ast.parse(
        INIT_PATH.read_text(encoding="utf-8"),
        filename=str(INIT_PATH),
    )
    for statement in module.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in statement.targets
        ):
            continue
        version = ast.literal_eval(statement.value)
        if not isinstance(version, str):
            break
        if SEMANTIC_VERSION_PATTERN.fullmatch(version) is None:
            raise ValueError(f"Invalid semantic version: {version}")
        return version
    raise ValueError(f"No string __version__ declaration in {INIT_PATH}")


def project_metadata() -> dict[str, Any]:
    """Return parsed project metadata from pyproject.toml."""
    with PYPROJECT_PATH.open("rb") as stream:
        return tomllib.load(stream)


def check_version() -> None:
    """Require a valid package version declaration."""
    print(f"version: {declared_version()}")


def check_project_metadata() -> None:
    """Require the metadata and build declarations used by publication."""
    metadata = project_metadata()
    project = metadata["project"]
    build_system = metadata["build-system"]
    hatch_version = metadata["tool"]["hatch"]["version"]
    expected = {
        "project.name": (project["name"], "pyqt-reactive"),
        "build-system.build-backend": (
            build_system["build-backend"],
            "hatchling.build",
        ),
        "tool.hatch.version.path": (
            hatch_version["path"],
            "src/pyqt_reactive/__init__.py",
        ),
    }
    mismatches = {
        field: {"actual": actual, "expected": required}
        for field, (actual, required) in expected.items()
        if actual != required
    }
    if mismatches:
        raise ValueError(f"Invalid project metadata: {mismatches}")
    if not project.get("description") or not project.get("authors"):
        raise ValueError("Project description and authors are required")
    if not README_PATH.read_text(encoding="utf-8").strip():
        raise ValueError("README.md must not be empty")


def check_publish_workflow() -> None:
    """Require tag publication through GitHub trusted publishing."""
    workflow = PUBLISH_WORKFLOW_PATH.read_text(encoding="utf-8")
    required_fragments = (
        "tags:",
        "id-token: write",
        "pypa/gh-action-pypi-publish@release/v1",
    )
    missing = tuple(fragment for fragment in required_fragments if fragment not in workflow)
    if missing:
        raise ValueError(f"Publish workflow is missing declarations: {missing}")


def check_git_branch() -> None:
    """Require release verification from the canonical branch."""
    branch = subprocess.run(
        ("git", "branch", "--show-current"),
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if branch != "main":
        raise ValueError(f"Release verification requires main, found {branch!r}")


def check_distribution() -> None:
    """Build both artifacts and validate their package metadata."""
    for generated_path in (DIST_PATH, BUILD_PATH):
        if generated_path.exists():
            shutil.rmtree(generated_path)
    subprocess.run(
        (sys.executable, "-m", "build"),
        cwd=PROJECT_ROOT,
        check=True,
    )
    artifacts = tuple(DIST_PATH.iterdir())
    names = {artifact.name for artifact in artifacts}
    if len(artifacts) != 2 or not any(name.endswith(".whl") for name in names):
        raise ValueError(f"Expected one wheel and one source archive, found {names}")
    if not any(name.endswith(".tar.gz") for name in names):
        raise ValueError(f"Source archive missing from {names}")
    subprocess.run(
        (
            sys.executable,
            "-m",
            "twine",
            "check",
            *(str(path) for path in artifacts),
        ),
        cwd=PROJECT_ROOT,
        check=True,
    )


def main() -> int:
    """Run every release gate and report its authoritative result."""
    checks: tuple[tuple[str, Callable[[], None]], ...] = (
        ("version", check_version),
        ("project metadata", check_project_metadata),
        ("publish workflow", check_publish_workflow),
        ("git branch", check_git_branch),
        ("distribution", check_distribution),
    )
    for label, check in checks:
        print(f"checking {label}...", flush=True)
        check()
    print("pyqt-reactive release verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
