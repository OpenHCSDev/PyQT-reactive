"""Tests for declaration-owned preview metadata resolution."""

from dataclasses import dataclass

from objectstate.lazy_factory import PREVIEW_LABEL_REGISTRY, LazyDataclassFactory
from python_introspect import Enableable

from pyqt_reactive.utils.preview_formatters import resolve_preview_label
from pyqt_reactive.widgets.shared.manager_preview_formatting import (
    ManagerPreviewFieldFormatter,
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
    assert ManagerPreviewFieldFormatter().format_field("config", lazy_type()) == "BASE"


def test_manager_preview_respects_nominal_enableable_state(monkeypatch) -> None:
    @dataclass(frozen=True)
    class FeatureConfig(Enableable):
        pass

    monkeypatch.setitem(PREVIEW_LABEL_REGISTRY, FeatureConfig, "FEATURE")
    formatter = ManagerPreviewFieldFormatter()

    assert formatter.format_field("feature", FeatureConfig(enabled=False)) is None
    assert formatter.format_field("feature", FeatureConfig(enabled=True)) == "FEATURE"
