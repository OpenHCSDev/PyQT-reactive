"""Declaration-owned path-name inference behavior."""

import pytest

from pyqt_reactive.widgets.enhanced_path_widget import (
    PATH_NAME_ROLE_CLASSIFIER,
    PathBehaviorDetector,
    PathNameRole,
    PathParameterNameTokens,
)


@pytest.mark.parametrize(
    ("parameter_name", "expected_role"),
    (
        ("output_directory", PathNameRole.DIRECTORY),
        ("inputFile", PathNameRole.FILE),
        ("pipeline_path", PathNameRole.PIPELINE),
        ("step_path", PathNameRole.STEP),
        ("custom_func_path", PathNameRole.FUNCTION),
    ),
)
def test_path_role_owns_classification_tokens_and_behavior(
    parameter_name: str,
    expected_role: PathNameRole,
) -> None:
    role = PATH_NAME_ROLE_CLASSIFIER.classify(PathParameterNameTokens.parse(parameter_name))

    assert role is expected_role
    assert PathBehaviorDetector._detect_from_parameter_name(parameter_name) == role.behavior
