"""Declarative manager item display construction."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field, is_dataclass

from objectstate import DottedFieldPath, ObjectState, ObjectStateRegistry
from objectstate.lazy_factory import ALWAYS_VIEWABLE_FIELDS_REGISTRY
from python_introspect import Enableable, is_enableable

from pyqt_reactive.strategies.preview_formatting import (
    ObjectStatePreviewFormattingService,
    PreviewSegment,
)
from pyqt_reactive.utils.preview_formatters import (
    PreviewFieldFormatRequest,
    canonical_declaration_mro,
)
from pyqt_reactive.widgets.shared.list_item_delegate import Segment, StyledText, StyledTextLayout

logger = logging.getLogger(__name__)

FieldFormatter = Callable[[object], str | None]


@dataclass(frozen=True)
class ListItemFormat:
    """Type-safe declarative configuration for list item display format."""

    first_line: tuple[str, ...] = ()
    preview_line: tuple[str, ...] = ()
    detail_line_field: str | None = None
    formatters: dict[str, FieldFormatter] = field(default_factory=dict)
    append_signature_diff_fields: bool = True

    def __post_init__(self) -> None:
        """Reject string-named or otherwise non-callable formatter dispatch."""
        invalid_paths = tuple(
            field_path
            for field_path, formatter in self.formatters.items()
            if not callable(formatter)
        )
        if invalid_paths:
            raise TypeError(
                "List-item formatters must be callables for paths: " + ", ".join(invalid_paths)
            )


class _ManagerItemDisplayBuilder:
    """Builds StyledText rows from ListItemFormat and ObjectState metadata."""

    def __init__(
        self,
        *,
        preview_formatter: ObjectStatePreviewFormattingService,
        field_formatter: Callable[[PreviewFieldFormatRequest], str | None],
        signature_diff_fields: Callable[[object], set[str]],
        scope_for_item: Callable[[object], str],
    ) -> None:
        self._preview_formatter = preview_formatter
        self._field_formatter = field_formatter
        self._signature_diff_fields = signature_diff_fields
        self._scope_for_item = scope_for_item

    def build_from_format(
        self,
        *,
        item: object,
        item_name: str,
        item_format: ListItemFormat | None,
        status_prefix: str = "",
        detail_line: str = "",
    ) -> StyledText:
        if item_format is None:
            return self.build_multiline(
                item_name=item_name,
                segments=[],
                status_prefix=status_prefix,
                detail_line=detail_line,
                first_line_segments=[],
            )

        scope_id = self._scope_for_item(item)
        state = ObjectStateRegistry.get_by_scope(scope_id)

        first_line_segments = self._preview_formatter.collect_and_render(
            state,
            list(item_format.first_line),
            item_format.formatters,
            self._field_formatter,
        )
        preview_segments = self._preview_formatter.collect_and_render(
            state,
            list(item_format.preview_line),
            item_format.formatters,
            self._field_formatter,
        )

        always_viewable = self._discover_always_viewable_fields(state)
        if always_viewable:
            logger.debug("PREVIEW: Adding always_viewable fields to preview: %s", always_viewable)
            always_viewable_segments = self._preview_formatter.collect_and_render(
                state,
                list(always_viewable),
                item_format.formatters,
                self._field_formatter,
            )
            if preview_segments and always_viewable_segments:
                first_seg = always_viewable_segments[0]
                always_viewable_segments[0] = (first_seg[0], first_seg[1], " | ")
            preview_segments.extend(always_viewable_segments)

        if detail_line == "" and item_format.detail_line_field is not None and state is not None:
            resolved_detail = state.get_resolved_value(item_format.detail_line_field)
            if resolved_detail is not None:
                detail_line = str(resolved_detail)

        if item_format.append_signature_diff_fields:
            self._append_signature_diff_segments(
                item=item,
                state=state,
                segments=preview_segments,
                first_line_segments=first_line_segments,
            )

        styled = self.build_multiline(
            item_name=item_name,
            segments=preview_segments,
            status_prefix=status_prefix,
            detail_line=detail_line,
            first_line_segments=first_line_segments,
        )
        return styled

    def build_multiline(
        self,
        *,
        item_name: str,
        segments: list[PreviewSegment],
        status_prefix: str = "",
        detail_line: str = "",
        first_line_segments: list[PreviewSegment],
    ) -> StyledText:
        layout = StyledTextLayout(
            name=Segment(text=item_name, field_path="", asterisk_prefix=True),
            status_prefix=status_prefix,
            first_line_segments=self._create_segments_with_grouping(first_line_segments),
            detail_line=detail_line,
            preview_segments=self._create_segments_with_grouping(
                segments,
                sep_before_first=" | ",
                asterisk_prefix=True,
            ),
            config_segments=[],
            multiline=True,
        )
        return StyledText(layout)

    def _append_signature_diff_segments(
        self,
        *,
        item: object,
        state: ObjectState | None,
        segments: list[PreviewSegment],
        first_line_segments: list[PreviewSegment],
    ) -> None:
        if state is None:
            return
        sig_diff_fields = self._signature_diff_fields(item)
        existing_paths = {field_path for _, field_path, _ in segments if field_path}
        existing_paths.update(field_path for _, field_path, _ in first_line_segments if field_path)

        sig_diff_paths_to_add = [
            field_path
            for field_path in sig_diff_fields
            if field_path != "name"
            and not any(DottedFieldPath(path).contains_path(field_path) for path in existing_paths)
        ]
        if not sig_diff_paths_to_add:
            return

        sig_diff_segments = self._preview_formatter.collect_and_render(
            state,
            sig_diff_paths_to_add,
            {},
            self._field_formatter,
        )
        if segments and sig_diff_segments:
            first_label, first_path, _ = sig_diff_segments[0]
            sig_diff_segments[0] = (first_label, first_path, " | ")
        segments.extend(sig_diff_segments)

    def _discover_always_viewable_fields(
        self,
        state: ObjectState | None,
    ) -> tuple[str, ...]:
        if state is None:
            return ()

        always_viewable = []
        seen = set()

        def add_field_path(field_path: str) -> None:
            if field_path in seen:
                return
            seen.add(field_path)
            always_viewable.append(field_path)

        container_paths = ("",) + tuple(
            path for path in state.parameters if state.has_parameter_descendants(path)
        )
        for path in container_paths:
            config_type = state.type_for_path(path)
            if not is_dataclass(config_type):
                continue

            is_enabled = True
            if is_enableable(config_type):
                enabled_field = Enableable.require_parameter_name()
                enabled_path = f"{path}.{enabled_field}" if path else enabled_field
                resolved_enabled = state.get_resolved_value(enabled_path)
                is_enabled = resolved_enabled is True
                if is_enabled:
                    add_field_path(enabled_path)
                    logger.debug(
                        "PREVIEW: Added enabled field %s for %s",
                        enabled_path,
                        config_type.__name__,
                    )

            registered_fields = self._registered_always_viewable_fields(config_type)
            if not registered_fields:
                continue

            if not is_enabled:
                logger.debug(
                    "PREVIEW: Skipping always_viewable fields for %s - enabled=%s",
                    config_type.__name__,
                    resolved_enabled,
                )
                continue

            for field_name in registered_fields:
                full_path = f"{path}.{field_name}" if path else field_name
                add_field_path(full_path)
                logger.debug(
                    "PREVIEW: Added always_viewable field %s for %s",
                    full_path,
                    config_type.__name__,
                )

        return tuple(always_viewable)

    @staticmethod
    def _registered_always_viewable_fields(config_type: type) -> tuple[str, ...] | None:
        for declaration_type in canonical_declaration_mro(config_type):
            registered_fields = ALWAYS_VIEWABLE_FIELDS_REGISTRY.get(declaration_type)
            if registered_fields is not None:
                return tuple(registered_fields)
        return None

    @staticmethod
    def _create_segments_with_grouping(
        segments_list: list[PreviewSegment],
        sep_before_first: str | None = None,
        asterisk_prefix: bool = False,
    ) -> list[Segment]:
        result = []
        for index, (label, path, declared_separator) in enumerate(segments_list):
            if declared_separator is not None:
                sep_before = declared_separator
            elif index > 0:
                sep_before = sep_before_first
            else:
                sep_before = None
            result.append(
                Segment(
                    text=label,
                    field_path=path,
                    sep_before=sep_before,
                    asterisk_prefix=asterisk_prefix,
                )
            )
        return result
