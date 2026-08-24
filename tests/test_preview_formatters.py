"""Tests for declaration-owned preview metadata resolution."""

from dataclasses import dataclass

import pytest
from objectstate.lazy_factory import (
    FIELD_ABBREVIATIONS_REGISTRY,
    GROUP_ABBREVIATIONS_REGISTRY,
    PREVIEW_LABEL_REGISTRY,
    LazyDataclassFactory,
)
from python_introspect import Enableable

from pyqt_reactive.strategies.preview_formatting import (
    FormattingConfig,
    ObjectStatePreviewFormattingService,
)
from pyqt_reactive.utils.preview_formatters import (
    PreviewFieldFormatRequest,
    resolve_field_abbreviation,
    resolve_preview_label,
)
from pyqt_reactive.widgets.shared.manager_item_display_builder import (
    ListItemFormat,
    _ManagerItemDisplayBuilder,
)
from pyqt_reactive.widgets.shared.manager_preview_formatting import (
    ManagerPreviewFieldFormatter,
)


def _request(
    field_path: str,
    value: object,
    field_owner: type,
) -> PreviewFieldFormatRequest:
    return PreviewFieldFormatRequest(
        field_path=field_path,
        value=value,
        field_owner=field_owner,
    )


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
        ManagerPreviewFieldFormatter().format_field(_request("config", lazy_type(), lazy_type))
        == "BASE"
    )


def test_manager_preview_respects_nominal_enableable_state(monkeypatch) -> None:
    @dataclass(frozen=True)
    class FeatureConfig(Enableable):
        pass

    monkeypatch.setitem(PREVIEW_LABEL_REGISTRY, FeatureConfig, "FEATURE")
    formatter = ManagerPreviewFieldFormatter()

    assert (
        formatter.format_field(_request("feature", FeatureConfig(enabled=False), FeatureConfig))
        is None
    )
    assert (
        formatter.format_field(_request("feature", FeatureConfig(enabled=True), FeatureConfig))
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

    service = ObjectStatePreviewFormattingService(FormattingConfig(show_group_labels=False))
    segments = service.collect_and_render(
        State(),
        ["nested.value"],
        {},
        format_request,
    )

    assert requests == [
        _request("nested.value", 5, NestedConfig),
    ]
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
