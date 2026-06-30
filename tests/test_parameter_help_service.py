"""Tests for shared parameter help introspection."""

from dataclasses import dataclass


def test_dataclass_docstring_help_falls_back_when_source_is_unavailable(monkeypatch):
    from pyqt_reactive.services import parameter_help_service
    from pyqt_reactive.services.parameter_help_service import docstring_info_for_target

    @dataclass
    class GeneratedLikeConfig:
        """Generated-like config summary."""

        value: int = 1

    def raise_source_unavailable(_target):
        raise OSError("could not find class definition")

    monkeypatch.setattr(
        parameter_help_service.inspect,
        "getsource",
        raise_source_unavailable,
    )

    docstring_info = docstring_info_for_target(GeneratedLikeConfig)

    assert docstring_info.summary == "Generated-like config summary."
    assert docstring_info.description is None
