"""Path-name roles and dialog contexts are open, registered families."""

import pytest

from formbridge.core.path_cache import (
    DirectorySelection,
    FileSelection,
    PathCacheKey,
    UnifiedPathCache,
)
from pyqt_reactive.widgets.enhanced_path_widget import (
    DEFAULT_PATH_BEHAVIOR,
    DirectoryPathRole,
    FilePathRole,
    PathBehaviorDetector,
    PathNameRole,
    PathParameterNameTokens,
)


@pytest.mark.parametrize(
    ("parameter_name", "expected_role"),
    (
        ("output_directory", DirectoryPathRole),
        ("inputFile", FilePathRole),
        ("source_folder", DirectoryPathRole),
    ),
)
def test_path_role_owns_classification_tokens_and_behavior(
    parameter_name: str,
    expected_role: type[PathNameRole],
) -> None:
    role = PathNameRole.for_tokens(PathParameterNameTokens.parse(parameter_name))

    assert role is expected_role
    assert PathBehaviorDetector._detect_from_parameter_name(parameter_name) == role.behavior


def test_name_without_a_role_word_gets_the_default_behavior() -> None:
    assert PathBehaviorDetector.detect_behavior("pipeline_path") == DEFAULT_PATH_BEHAVIOR


def test_application_declares_its_own_dialog_context(tmp_path) -> None:
    class SampleImport(PathCacheKey):
        """A context declared outside the library."""

    try:
        cache = UnifiedPathCache(tmp_path / "paths.json")
        cache.set_cached_path(SampleImport, tmp_path)
        cache.set_cached_path(DirectorySelection, tmp_path)

        reloaded = UnifiedPathCache(tmp_path / "paths.json")
        assert SampleImport.stored_key == "sample_import"
        assert PathCacheKey.__registry__["sample_import"] is SampleImport
        assert reloaded.get_initial_path(SampleImport) == tmp_path
        assert reloaded.get_cached_path(FileSelection) is None
    finally:
        del PathCacheKey.__registry__["sample_import"]
