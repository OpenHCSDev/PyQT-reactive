"""Declaration-driven formatting for manager list-item previews."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeAlias

from objectstate import DottedFieldPath, ParameterOwner

from pyqt_reactive.utils.preview_formatters import (
    PreviewFieldFormatRequest,
    canonical_declaration_mro,
)

if TYPE_CHECKING:
    from objectstate import ObjectState

PreviewSegment: TypeAlias = tuple[str, str | None, str | None]
PreviewValueFormatter: TypeAlias = Callable[[PreviewFieldFormatRequest], str | None]
ItemValueFormatter: TypeAlias = Callable[[object], str | None]


def get_group_abbreviation(config_type: type) -> str:
    """Resolve a group abbreviation from the canonical declaration MRO."""
    from objectstate.lazy_factory import GROUP_ABBREVIATIONS_REGISTRY

    for declaration_type in canonical_declaration_mro(config_type):
        abbreviation = GROUP_ABBREVIATIONS_REGISTRY.get(declaration_type)
        if abbreviation is not None:
            return abbreviation
    return config_type.__name__.split("_", 1)[0]


@dataclass(frozen=True, slots=True)
class FormattingConfig:
    """Presentation rules for preview grouping and separators."""

    show_group_labels: bool = True
    group_separator: str = " | "
    field_separator: str = ", "
    closing_brace_separator: str = ""
    container_abbr_func: Callable[[type], str] = get_group_abbreviation


@dataclass(frozen=True, slots=True)
class _PreviewField:
    """One rendered field in a preview group."""

    field_path: str
    label: str


@dataclass(slots=True)
class _PreviewGroup:
    """Fields sharing one authoritative ObjectState container path."""

    container_path: DottedFieldPath
    owner: ParameterOwner
    fields: list[_PreviewField] = field(default_factory=list)

    def add(self, field_path: str, label: str) -> None:
        """Append one field to this render-cycle projection."""
        self.fields.append(_PreviewField(field_path=field_path, label=label))

    def heading(self, config: FormattingConfig) -> tuple[str, str | None]:
        """Derive the heading from the ObjectState container path and owner."""
        if not self.container_path.parts:
            return "root", None
        if not isinstance(self.owner, type):
            raise TypeError(
                f"Preview container {self.container_path.value!r} requires a type declaration"
            )
        return (
            config.container_abbr_func(self.owner),
            self.container_path.value,
        )


class _PreviewSegmentBuilder:
    """Group formatted fields without copying their declaration metadata."""

    def __init__(self, formatting_config: FormattingConfig) -> None:
        self.config = formatting_config
        self._groups: dict[DottedFieldPath, _PreviewGroup] = {}

    def add_field(
        self,
        field_path: str,
        label: str,
        container_path: DottedFieldPath,
        container_owner: ParameterOwner,
    ) -> None:
        """Add a formatted field to its declaration-owned presentation group."""
        group = self._groups.get(container_path)
        if group is None:
            group = _PreviewGroup(
                container_path=container_path,
                owner=container_owner,
            )
            self._groups[container_path] = group
        elif group.owner is not container_owner:
            raise TypeError(
                f"Preview container {container_path.value!r} has inconsistent declarations"
            )
        group.add(field_path, label)

    def build(self) -> list[PreviewSegment]:
        """Render groups in the order their first field was added."""
        segments: list[PreviewSegment] = []
        for index, group in enumerate(self._groups.values()):
            segments.extend(self._render_group(group, is_first_group=index == 0))
        return segments

    def _render_group(
        self,
        group: _PreviewGroup,
        *,
        is_first_group: bool,
    ) -> list[PreviewSegment]:
        segments: list[PreviewSegment] = []
        if self.config.show_group_labels:
            abbreviation, abbreviation_path = group.heading(self.config)
            if is_first_group:
                group_separator = ""
            else:
                group_separator = self.config.group_separator
            segments.extend(
                (
                    (abbreviation, abbreviation_path, group_separator),
                    ("{", None, ""),
                )
            )

        for index, preview_field in enumerate(group.fields):
            if index == 0:
                if self.config.show_group_labels:
                    separator = ""
                else:
                    separator = None
            else:
                separator = self.config.field_separator
            segments.append((preview_field.label, preview_field.field_path, separator))

        if self.config.show_group_labels:
            segments.append(("}", None, self.config.closing_brace_separator))
        return segments


class ObjectStatePreviewFormattingService:
    """Format resolved ObjectState values using their recorded declarations."""

    def __init__(self, config: FormattingConfig) -> None:
        self.config = config

    def collect_and_render(
        self,
        state: ObjectState | None,
        field_paths: Sequence[str],
        formatters: Mapping[str, ItemValueFormatter],
        field_value_formatter: PreviewValueFormatter,
    ) -> list[PreviewSegment]:
        """Collect declared fields and return their rendered segments."""
        if state is None:
            return []

        builder = _PreviewSegmentBuilder(self.config)
        for field_path in field_paths:
            value = state.get_resolved_value(field_path)
            if value is None:
                continue

            field_owner = self._field_owner_for_path(state, field_path)
            formatter = formatters.get(field_path)
            if formatter is None:
                label = field_value_formatter(
                    PreviewFieldFormatRequest(
                        field_path=field_path,
                        value=value,
                        field_owner=field_owner,
                    )
                )
            else:
                label = formatter(value)
            if not label:
                continue

            container_path = self._container_path(field_path)
            builder.add_field(
                field_path,
                label,
                container_path,
                self._field_owner_for_path(state, container_path.value),
            )
        return builder.build()

    @staticmethod
    def _field_owner_for_path(
        state: ObjectState,
        field_path: str,
    ) -> ParameterOwner:
        declaration = state.type_for_path(field_path)
        if not isinstance(declaration, type) and not callable(declaration):
            raise TypeError(
                f"Preview field {field_path!r} requires a nominal type or callable declaration"
            )
        return declaration

    @staticmethod
    def _container_path(field_path: str) -> DottedFieldPath:
        if "." not in field_path:
            return DottedFieldPath("")
        return DottedFieldPath(field_path.rsplit(".", 1)[0])
