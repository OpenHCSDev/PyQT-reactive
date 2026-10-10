"""The original publisher resolves declared public runtime and test inputs."""

import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement

from scripts.verify_release_ready import project_metadata


def test_runtime_source_candidate_is_pinned_to_an_exact_commit():
    metadata = project_metadata()
    runtime = next(
        requirement for requirement in map(Requirement, metadata["project"]["dependencies"])
        if requirement.name == "zmqruntime"
    )
    assert runtime.specifier.contains("0.6.0")
    constraints = Path("requirements-ci.txt").read_text().splitlines()
    candidates = [
        Requirement(value)
        for value in constraints if value.strip() and not value.lstrip().startswith("#")
    ]
    # A source candidate is allowed only before coordinated publication and
    # only at an exact commit, so it can never drift from the declared bound.
    assert all(
        re.search(r"@[0-9a-f]{40}$", candidate.url or "")
        for candidate in candidates if candidate.name == runtime.name
    )


@pytest.mark.parametrize("name", ("qtpy", "vispy"))
def test_original_binding_controls_have_declared_test_dependencies(name):
    metadata = project_metadata()
    declared = {
        Requirement(value).name.casefold()
        for value in metadata["project"]["optional-dependencies"]["dev"]
    }
    assert name in declared
