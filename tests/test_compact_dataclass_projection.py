from dataclasses import dataclass, field

from pyqt_reactive.services.widget_tree_projection_config import (
    COMPACT_FIELD_PROJECTION_METADATA_KEY,
    CompactFieldProjection,
    compact_dataclass_projection,
)


@dataclass(frozen=True)
class _ProjectionExample:
    required_empty: str = field(
        metadata={
            COMPACT_FIELD_PROJECTION_METADATA_KEY: CompactFieldProjection(
                includes=lambda _owner, _value: True
            )
        }
    )
    ordinary_empty: str = ""
    enabled: bool = False
    selected: bool = field(
        default=False,
        metadata={
            COMPACT_FIELD_PROJECTION_METADATA_KEY: CompactFieldProjection(
                includes=lambda owner, value: value or owner.enabled
            )
        },
    )


def test_compact_dataclass_projection_uses_field_owned_predicates():
    value = _ProjectionExample(
        required_empty="",
        enabled=True,
        selected=False,
    )

    assert compact_dataclass_projection(value) == {
        "required_empty": "",
        "enabled": True,
        "selected": False,
    }


def test_compact_dataclass_projection_omits_default_empty_values():
    value = _ProjectionExample(required_empty="")

    assert compact_dataclass_projection(value) == {"required_empty": ""}
