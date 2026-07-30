"""Tests for shared parameter help introspection."""

from dataclasses import dataclass
from typing import Annotated

from pyqt_reactive.services.parameter_help_service import parameter_help_content


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


def test_parameter_help_projects_annotated_owner_type_without_metadata_repr() -> None:
    content = parameter_help_content(
        param_name="colormap",
        param_type=Annotated[str, "non-empty"],
        description="Napari colormap name.",
    )

    assert content.summary == "• colormap (str)"
    assert content.description == "Napari colormap name."
