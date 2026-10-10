"""The original publisher resolves declared public runtime and test inputs."""

from pathlib import Path

import pytest
from packaging.requirements import Requirement

from scripts.verify_release_ready import project_metadata


def test_published_runtime_is_not_overridden_by_a_source_candidate():
    metadata = project_metadata()
    runtime = next(
        requirement for requirement in map(Requirement, metadata["project"]["dependencies"])
        if requirement.name == "zmqruntime"
    )
    assert runtime.specifier.contains("0.3.0")
    constraints = Path("requirements-ci.txt").read_text().splitlines()
    assert not any(
        Requirement(value).name == runtime.name
        for value in constraints if value.strip() and not value.lstrip().startswith("#")
    )


@pytest.mark.parametrize("name", ("qtpy", "vispy"))
def test_original_binding_controls_have_declared_test_dependencies(name):
    metadata = project_metadata()
    declared = {
        Requirement(value).name.casefold()
        for value in metadata["project"]["optional-dependencies"]["dev"]
    }
    assert name in declared
