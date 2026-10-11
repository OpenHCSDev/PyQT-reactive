"""Tests for declaration-owned preview metadata resolution."""

from collections import UserDict, UserList
from dataclasses import dataclass, field, replace
from enum import StrEnum

import pytest
from objectstate.lazy_factory import (
    FIELD_ABBREVIATIONS_REGISTRY,
    GROUP_ABBREVIATIONS_REGISTRY,
    PREVIEW_LABEL_REGISTRY,
    LazyDataclassFactory,
)
from python_introspect import Enableable

from formbridge.strategies.preview_formatting import (
    FormattingConfig,
    ObjectStatePreviewFormattingService,
)
from formbridge.utils.preview_formatters import (
    PreviewFieldFormatRequest,
    PreviewValueDetail,
    format_preview_value,
    resolve_field_abbreviation,
    resolve_preview_label,
)
from pyqt_reactive.widgets.shared.manager_item_display_builder import (
    ListItemFormat,
    _ManagerItemDisplayBuilder,
)
from formbridge.managers.preview_formatting import ManagerPreviewFieldFormatter


def _request(
    field_path: str,
    value: object,
    field_owner: type,
) -> PreviewFieldFormatRequest:
    return PreviewFieldFormatRequest(
        field_path=field_path,
        value=value,
        field_owner=field_owner,
        value_formatter=FormattingConfig().format_value,
    )


def test_standalone_preview_request_uses_generic_formatter() -> None:
    request = PreviewFieldFormatRequest("config.values", (1, 2), object)
    assert request.field_name == "values"
    assert request.value_formatter is format_preview_value
    assert request.value_formatter(request.value) == "[2]"


def test_preview_label_resolves_from_nearest_declaration(monkeypatch) -> None:
    @dataclass
    class BaseConfig:
        value: int = 0

    @dataclass
    class SpecializedConfig(BaseConfig):
        pass

    @dataclass
    class InheritedConfig(BaseConfig):
        pass

    monkeypatch.setitem(PREVIEW_LABEL_REGISTRY, BaseConfig, "BASE")
    monkeypatch.setitem(PREVIEW_LABEL_REGISTRY, SpecializedConfig, "SPECIAL")

    inherited = resolve_preview_label(InheritedConfig())
    specialized = resolve_preview_label(SpecializedConfig())

    assert inherited is not None
    assert inherited.owner is BaseConfig
    assert inherited.label == "BASE"
    assert specialized is not None
    assert specialized.owner is SpecializedConfig
    assert specialized.label == "SPECIAL"


def test_lazy_wrapper_preserves_base_declaration_provenance(monkeypatch) -> None:
    @dataclass
    class BaseConfig:
        value: int = 0

    lazy_type = LazyDataclassFactory.make_lazy_simple(
        BaseConfig,
        "LazyPreviewFormatterBaseConfig",
    )
    monkeypatch.setitem(PREVIEW_LABEL_REGISTRY, BaseConfig, "BASE")
    monkeypatch.setitem(PREVIEW_LABEL_REGISTRY, lazy_type, "COPIED")

    resolution = resolve_preview_label(lazy_type())

    assert resolution is not None
    assert resolution.owner is BaseConfig
    assert resolution.label == "BASE"
    assert (
        ManagerPreviewFieldFormatter().format_field(
            _request("config", lazy_type(), lazy_type)
        )
        == "BASE"
    )


def test_manager_preview_respects_nominal_enableable_state(monkeypatch) -> None:
    @dataclass(frozen=True)
    class FeatureConfig(Enableable):
        pass

    monkeypatch.setitem(PREVIEW_LABEL_REGISTRY, FeatureConfig, "FEATURE")
    formatter = ManagerPreviewFieldFormatter()

    assert (
        formatter.format_field(
            _request("feature", FeatureConfig(enabled=False), FeatureConfig)
        )
        is None
    )
    assert (
        formatter.format_field(
            _request("feature", FeatureConfig(enabled=True), FeatureConfig)
        )
        == "FEATURE"
    )


def test_field_abbreviation_resolves_only_from_owning_declaration(monkeypatch) -> None:
    @dataclass
    class FirstConfig:
        value: int = 0

    @dataclass
    class SecondConfig:
        value: int = 0

    @dataclass
    class UnrelatedConfig:
        value: int = 0

    monkeypatch.setitem(FIELD_ABBREVIATIONS_REGISTRY, FirstConfig, {"value": "first"})
    monkeypatch.setitem(FIELD_ABBREVIATIONS_REGISTRY, SecondConfig, {"value": "second"})
    formatter = ManagerPreviewFieldFormatter()

    assert formatter.format_field(_request("value", 1, SecondConfig)) == "second:1"
    assert formatter.format_field(_request("value", 1, UnrelatedConfig)) == "value:1"


def test_callable_field_owner_uses_generic_value_presentation() -> None:
    def operation(value: int = 1) -> None:
        del value

    formatter = ManagerPreviewFieldFormatter()

    assert formatter.format_field(_request("value", 1, operation)) == "value:1"


def test_lazy_field_abbreviation_preserves_base_declaration_provenance(
    monkeypatch,
) -> None:
    @dataclass
    class BaseConfig:
        value: int = 0

    lazy_type = LazyDataclassFactory.make_lazy_simple(
        BaseConfig,
        "LazyPreviewFieldAbbreviationBaseConfig",
    )
    monkeypatch.setitem(FIELD_ABBREVIATIONS_REGISTRY, BaseConfig, {"value": "base"})
    monkeypatch.setitem(FIELD_ABBREVIATIONS_REGISTRY, lazy_type, {"value": "copied"})

    resolution = resolve_field_abbreviation(lazy_type, "value")

    assert resolution is not None
    assert resolution.owner is BaseConfig
    assert resolution.abbreviation == "base"


def test_preview_strategy_supplies_objectstate_declaration_to_formatter() -> None:
    @dataclass
    class NestedConfig:
        value: int = 5

    class State:
        def get_resolved_value(self, field_path: str) -> int:
            assert field_path == "nested.value"
            return 5

        def type_for_path(self, field_path: str) -> type:
            assert field_path in {"nested", "nested.value"}
            return NestedConfig

    requests: list[PreviewFieldFormatRequest] = []

    def format_request(request: PreviewFieldFormatRequest) -> str:
        requests.append(request)
        return "owned:5"

    service = ObjectStatePreviewFormattingService(
        FormattingConfig(show_group_labels=False)
    )
    segments = service.collect_and_render(
        State(),
        ["nested.value"],
        {},
        format_request,
    )

    assert len(requests) == 1
    assert requests[0].field_owner is NestedConfig
    assert requests[0].field_path == "nested.value"
    assert requests[0].value == 5
    assert requests[0].value_formatter == service.config.format_value
    assert segments == [("owned:5", "nested.value", None)]


def test_preview_groups_derive_identity_and_order_from_declared_types(
    monkeypatch,
) -> None:
    @dataclass
    class Config:
        first: int = 1
        second: int = 2

    lazy_type = LazyDataclassFactory.make_lazy_simple(
        Config,
        "LazyPreviewGroupConfig",
    )
    monkeypatch.setitem(GROUP_ABBREVIATIONS_REGISTRY, Config, "cfg")
    monkeypatch.setitem(GROUP_ABBREVIATIONS_REGISTRY, lazy_type, "copied")
    values = {
        "workers": 4,
        "config.first": 1,
        "config.second": 2,
    }
    types = {
        "": object,
        "workers": Config,
        "config": lazy_type,
        "config.first": lazy_type,
        "config.second": lazy_type,
    }

    class State:
        def get_resolved_value(self, field_path: str) -> int:
            return values[field_path]

        def type_for_path(self, field_path: str) -> type:
            return types[field_path]

    service = ObjectStatePreviewFormattingService(FormattingConfig())
    segments = service.collect_and_render(
        State(),
        tuple(values),
        {},
        lambda request: f"{request.field_name}:{request.value}",
    )

    assert segments == [
        ("root", None, ""),
        ("{", None, ""),
        ("workers:4", "workers", ""),
        ("}", None, ""),
        ("cfg", "config", " | "),
        ("{", None, ""),
        ("first:1", "config.first", ""),
        ("second:2", "config.second", ", "),
        ("}", None, ""),
    ]


def test_preview_groups_keep_distinct_paths_with_the_same_declaration(
    monkeypatch,
) -> None:
    @dataclass
    class Config:
        value: int = 1

    monkeypatch.setitem(GROUP_ABBREVIATIONS_REGISTRY, Config, "cfg")
    values = {"left.value": 1, "right.value": 2}

    class State:
        def get_resolved_value(self, field_path: str) -> int:
            return values[field_path]

        def type_for_path(self, field_path: str) -> type:
            assert field_path in {"left", "right", "left.value", "right.value"}
            return Config

    service = ObjectStatePreviewFormattingService(FormattingConfig())

    assert service.collect_and_render(
        State(),
        tuple(values),
        {},
        lambda request: f"{request.field_name}:{request.value}",
    ) == [
        ("cfg", "left", ""),
        ("{", None, ""),
        ("value:1", "left.value", ""),
        ("}", None, ""),
        ("cfg", "right", " | "),
        ("{", None, ""),
        ("value:2", "right.value", ""),
        ("}", None, ""),
    ]


def test_list_item_format_requires_explicit_callable_formatters() -> None:
    with pytest.raises(TypeError, match="must be callables.*value"):
        ListItemFormat(formatters={"value": "format_value"})  # type: ignore[dict-item]


def test_always_viewable_discovery_projects_only_from_parameter_containers(
    monkeypatch,
) -> None:
    @dataclass
    class NestedConfig:
        value: int = 1
        highlighted: int = 2

    from objectstate.lazy_factory import ALWAYS_VIEWABLE_FIELDS_REGISTRY

    monkeypatch.setitem(
        ALWAYS_VIEWABLE_FIELDS_REGISTRY,
        NestedConfig,
        ("highlighted",),
    )

    class State:
        parameters = {
            "nested": NestedConfig(),
            "nested.value": 1,
            "nested.highlighted": 2,
        }

        def has_parameter_descendants(self, field_path: str) -> bool:
            return field_path == "nested"

        def type_for_path(self, field_path: str) -> type:
            return NestedConfig if field_path == "nested" else int

        def get_resolved_value(self, field_path: str) -> object:
            return self.parameters[field_path]

    state = State()
    builder = _ManagerItemDisplayBuilder(
        preview_formatter=ObjectStatePreviewFormattingService(FormattingConfig()),
        field_formatter=ManagerPreviewFieldFormatter().format_field,
        signature_diff_fields=lambda _item: set(),
        scope_for_item=lambda _item: "scope",
    )

    assert builder._discover_always_viewable_fields(state) == ("nested.highlighted",)


@dataclass(frozen=True)
class _PreviewBinding:
    alias: str


@pytest.mark.parametrize(
    "value",
    [
        (_PreviewBinding("neuron"), _PreviewBinding("nucleus")),
        [_PreviewBinding("neuron"), _PreviewBinding("nucleus")],
        {"neuron": _PreviewBinding("neuron"), "nucleus": _PreviewBinding("nucleus")},
        UserDict({"neuron": 1, "nucleus": 2}),
        UserList([1, 2]),
        {_PreviewBinding("neuron"), _PreviewBinding("nucleus")},
        frozenset({1, 2}),
    ],
)
def test_compact_aggregate_previews_are_counts_without_recursive_repr(value):
    assert format_preview_value(value) == "[2]"
    assert FormattingConfig().format_value(value) == "[2]"


def test_compact_preview_does_not_even_compute_member_repr():
    class ExpensiveValue:
        def __repr__(self):
            raise AssertionError("Compact previews must not evaluate nested repr")

    assert format_preview_value((ExpensiveValue(),)) == "[1]"


def test_sequence_formatting_preserves_enum_names_and_handles_mixed_values():
    class Axis(StrEnum):
        CHANNEL = "channel"
        SITE = "site"

    assert format_preview_value(Axis.CHANNEL) == "CHANNEL"
    assert format_preview_value((Axis.CHANNEL, Axis.SITE)) == "channel,site"
    assert format_preview_value([Axis.CHANNEL, "custom"]) == "[2]"
    assert format_preview_value("a/path/to/images") == "a/path/to/images"
    for empty in ([], (), {}, set(), frozenset()):
        assert format_preview_value(empty) is None


def test_expanded_preview_and_length_limit_only_change_display_text():
    value = (_PreviewBinding("neurons"), _PreviewBinding("nuclei"))
    full = FormattingConfig(
        collection_detail=PreviewValueDetail.EXPANDED, max_value_length=0
    )
    assert full.format_value(value) == repr(value)
    bounded = replace(full, max_value_length=16)
    request = PreviewFieldFormatRequest(
        "source.bindings", value, _PreviewBinding, bounded.format_value
    )
    label = ManagerPreviewFieldFormatter().format_field(request)
    assert label == "bindings:" + repr(value)[:15] + "…"
    assert request.value is value
    assert request.field_path == "source.bindings"
    assert FormattingConfig(max_value_length=1).format_value("long") == "…"
    with pytest.raises(ValueError, match="non-negative"):
        FormattingConfig(max_value_length=-1)


def test_preview_rules_select_paths_once_before_grouping(monkeypatch):
    from objectstate import ObjectState, ObjectStateRegistry
    from objectstate.lazy_factory import ALWAYS_VIEWABLE_FIELDS_REGISTRY

    @dataclass
    class Nested:
        first: int = 1
        second: int = 2
        active: int = 3

    @dataclass
    class Config:
        nested: Nested = field(default_factory=Nested)

    import objectstate.config as framework_config

    monkeypatch.setattr(framework_config, "_base_config_type", Config)
    state = ObjectState(Config(), scope_id="preview-policy")
    monkeypatch.setattr(ObjectStateRegistry, "get_by_scope", lambda _scope: state)
    monkeypatch.setitem(ALWAYS_VIEWABLE_FIELDS_REGISTRY, Nested, ("first", "active"))
    monkeypatch.setitem(PREVIEW_LABEL_REGISTRY, Nested, "NEST")
    service = ObjectStatePreviewFormattingService(FormattingConfig())
    builder = _ManagerItemDisplayBuilder(
        preview_formatter=service,
        field_formatter=ManagerPreviewFieldFormatter().format_field,
        signature_diff_fields=lambda _: {"nested", "nested.first", "nested.second"},
        scope_for_item=lambda _: "preview-policy",
    )

    def display():
        return builder.build_from_format(
            item=object(),
            item_name="row",
            detail_line="full/path",
            item_format=ListItemFormat(preview_line=("nested.first",)),
        ).layout

    layout = display()
    paths = [span.field_path for span in layout.preview_segments]
    assert paths.count("nested.first") == 1
    assert paths.count("nested") == 1
    assert not any(span.text == "NEST" for span in layout.preview_segments)
    assert "nested.second" in paths  # Group headings must not suppress sibling changes.
    assert "nested.active" in paths
    assert layout.detail_line == "full/path"

    service.config = replace(
        service.config,
        show_modified_fields=False,
        show_active_configs=False,
        show_detail_line=False,
    )
    layout = display()
    paths = [span.field_path for span in layout.preview_segments]
    assert "nested.first" in paths
    assert "nested.second" not in paths
    assert "nested.active" not in paths
    assert layout.detail_line == ""
