from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pyqt_reactive.forms.parameter_form_service import ParameterFormService


class MatchSubject(Enum):
    FILE = "file"
    DIRECTORY = "directory"


@dataclass(frozen=True)
class MatchClause:
    subject: MatchSubject
    value: str | None = None


def test_convert_value_to_type_rebuilds_optional_dataclass_tuple() -> None:
    converted = ParameterFormService().convert_value_to_type(
        [{"subject": "directory", "value": "TimePoint_1"}],
        tuple[MatchClause, ...] | None,
        "source_filters",
    )

    assert converted == (
        MatchClause(subject=MatchSubject.DIRECTORY, value="TimePoint_1"),
    )
