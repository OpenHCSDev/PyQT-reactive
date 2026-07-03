from __future__ import annotations

from dataclasses import dataclass, field

from objectstate import DottedFieldPath
from pyqt_reactive.forms.parameter_form_tree_index import ParameterFormTreeIndex
from pyqt_reactive.forms.parameter_form_chrome_sync import ParameterFormChromeSync


@dataclass
class FakeManager:
    field_id: str
    nested_managers: dict[str, "FakeManager"] = field(default_factory=dict)
    widgets: dict[str, object] = field(default_factory=dict)
    _parent_manager: "FakeManager | None" = None
    form_tree: ParameterFormTreeIndex | None = None
    state: object | None = None
    chrome_sync: object | None = None


@dataclass
class FakeState:
    parameters: dict[str, object] = field(default_factory=dict)
    dirty_fields: set[str] = field(default_factory=set)
    signature_diff_fields: set[str] = field(default_factory=set)

    def get_resolved_value(self, _path: str) -> object | None:
        return None


@dataclass
class RecordingChromeSync:
    calls: list[set[str]] = field(default_factory=list)

    def refresh_widgets_for_paths(self, paths: set[str]) -> None:
        self.calls.append(set(paths))


def _manager_tree() -> tuple[ParameterFormTreeIndex, FakeManager, FakeManager, FakeManager]:
    root = FakeManager("")
    source_bindings = FakeManager("source_bindings", _parent_manager=root)
    source_filters = FakeManager(
        "source_bindings.source_filters",
        _parent_manager=source_bindings,
    )
    dtype_config = FakeManager("dtype_config", _parent_manager=root)
    source_bindings.nested_managers["source_filters"] = source_filters
    root.nested_managers["source_bindings"] = source_bindings
    root.nested_managers["dtype_config"] = dtype_config
    tree = ParameterFormTreeIndex(root)
    root.form_tree = tree
    root.state = FakeState()
    return tree, source_bindings, source_filters, dtype_config


def test_paths_for_manager_routes_by_dotted_scope_intersection() -> None:
    tree, source_bindings, source_filters, dtype_config = _manager_tree()
    paths = {
        "source_bindings.source_filters.0.match_type",
        "dtype_config.default_dtype_conversion",
    }

    assert tree.paths_for_manager(source_bindings, paths) == {
        "source_bindings.source_filters.0.match_type",
    }
    assert tree.paths_for_manager(source_filters, paths) == {
        "source_bindings.source_filters.0.match_type",
    }
    assert tree.paths_for_manager(dtype_config, paths) == {
        "dtype_config.default_dtype_conversion",
    }


def test_paths_for_manager_routes_container_path_to_descendants() -> None:
    tree, source_bindings, source_filters, dtype_config = _manager_tree()
    paths = {"source_bindings"}

    assert tree.paths_for_manager(source_bindings, paths) == {"source_bindings"}
    assert tree.paths_for_manager(source_filters, paths) == {"source_bindings"}
    assert tree.paths_for_manager(dtype_config, paths) == set()


def test_child_managers_for_paths_routes_only_direct_owners() -> None:
    tree, source_bindings, _, dtype_config = _manager_tree()
    root = source_bindings._parent_manager
    assert root is not None

    routes = {
        nested_manager.field_id: nested_paths
        for nested_manager, nested_paths in tree.child_managers_for_paths(
            root,
            {
                "source_bindings.source_filters.0.match_type",
                "dtype_config.default_dtype_conversion",
                "unrelated.value",
            },
        )
    }

    assert routes == {
        "source_bindings": {"source_bindings.source_filters.0.match_type"},
        "dtype_config": {"dtype_config.default_dtype_conversion"},
    }


def test_direct_child_field_for_path_uses_structural_objectstate_paths() -> None:
    """List element changes route to the owning dataclass field."""
    assert (
        ParameterFormTreeIndex.direct_child_field_for_path(
            "processing_config",
            "processing_config.variable_components[1]",
        )
        == "variable_components"
    )
    assert (
        ParameterFormTreeIndex.direct_child_field_for_path(
            "",
            "processing_config.variable_components[1]",
        )
        == "processing_config"
    )
    assert (
        ParameterFormTreeIndex.direct_child_field_for_path(
            "",
            "source_bindings.source_filters[0].match_type",
        )
        == "source_bindings"
    )


def test_matching_prefix_uses_deepest_containing_scope() -> None:
    tree, _, _, _ = _manager_tree()

    assert (
        tree.matching_prefix("source_bindings.source_filters.0.match_type")
        == "source_bindings.source_filters"
    )
    assert tree.matching_prefix("source_bindings") == "source_bindings"


def test_chrome_sync_routes_refresh_only_to_intersecting_nested_managers() -> None:
    _, source_bindings, _, dtype_config = _manager_tree()
    root = source_bindings._parent_manager
    source_bindings.chrome_sync = RecordingChromeSync()
    dtype_config.chrome_sync = RecordingChromeSync()

    assert root is not None
    ParameterFormChromeSync(root).refresh_widgets_for_paths(
        {"source_bindings.source_filters.0.match_type"}
    )

    assert source_bindings.chrome_sync.calls == [
        {"source_bindings.source_filters.0.match_type"}
    ]
    assert dtype_config.chrome_sync.calls == []


def test_chrome_sync_derives_inline_child_owner_paths_from_objectstate_paths() -> None:
    _, source_bindings, _, _ = _manager_tree()
    root = source_bindings._parent_manager
    assert root is not None

    chrome_sync = ParameterFormChromeSync(root)

    assert chrome_sync._compound_child_owner_paths(
        "source_bindings",
        {"source_bindings.source_filters"},
    ) == (DottedFieldPath("source_bindings.source_filters"),)
    assert chrome_sync._compound_child_owner_paths(
        "source_bindings",
        {"source_bindings.source_filters[0].match_type"},
    ) == (DottedFieldPath("source_bindings.source_filters"),)
    assert (
        chrome_sync._compound_child_owner_paths("source_bindings", {"source_bindings"})
        is None
    )
    assert chrome_sync._compound_child_owner_paths(
        "source_bindings",
        {"dtype_config.default_dtype_conversion"},
    ) == ()
