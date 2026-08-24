"""Preview formatter registration behavior."""

import pytest

from pyqt_reactive.protocols.preview_formatter import PreviewFormatterRegistry


def test_preview_formatter_resolves_nearest_nominal_base_registration() -> None:
    class BaseConfig:
        pass

    class SpecializedConfig(BaseConfig):
        pass

    PreviewFormatterRegistry.register(
        BaseConfig,
        lambda _config, field_name: f"base:{field_name}",
    )

    assert PreviewFormatterRegistry.format_field(SpecializedConfig(), "value") == ("base:value")


def test_preview_formatter_does_not_hide_host_formatter_failures() -> None:
    class BrokenConfig:
        pass

    def broken_formatter(_config: object, _field_name: str) -> str:
        raise RuntimeError("formatter failed")

    PreviewFormatterRegistry.register(BrokenConfig, broken_formatter)

    with pytest.raises(RuntimeError, match="formatter failed"):
        PreviewFormatterRegistry.format_field(BrokenConfig(), "value")
