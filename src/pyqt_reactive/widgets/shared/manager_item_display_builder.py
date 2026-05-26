"""Declarative manager item display construction."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, is_dataclass
from typing import Any, Callable, Optional, Union

from objectstate import ObjectStateRegistry
from objectstate.lazy_factory import ALWAYS_VIEWABLE_FIELDS_REGISTRY
from python_introspect import ENABLED_FIELD, is_enableable

from pyqt_reactive.widgets.shared.list_item_delegate import Segment, StyledText, StyledTextLayout

logger = logging.getLogger(__name__)

FieldFormatter = Union[str, Callable[[Any], Optional[str]]]


@dataclass(frozen=True)
class ListItemFormat:
    """Type-safe declarative configuration for list item display format."""

    first_line: tuple[str, ...] = ()
    preview_line: tuple[str, ...] = ()
    detail_line_field: Optional[str] = None
    formatters: dict[str, FieldFormatter] = field(default_factory=dict)


class _ManagerItemDisplayBuilder:
    """Builds StyledText rows from ListItemFormat and ObjectState metadata."""

    def __init__(
        self,
        *,
        preview_formatting_strategy: Any,
        field_formatter: Callable[[str, Any], Optional[str]],
        signature_diff_fields: Callable[[Any], set],
        scope_for_item: Callable[[Any], str],
    ) -> None:
        self._preview_formatting_strategy = preview_formatting_strategy
        self._field_formatter = field_formatter
        self._signature_diff_fields = signature_diff_fields
        self._scope_for_item = scope_for_item

    def build_from_format(
        self,
        *,
        item: Any,
        item_name: str,
        item_format: Optional[ListItemFormat],
        status_prefix: str = "",
        detail_line: str = "",
    ) -> StyledText:
        if item_format is None:
            return self.build_multiline(
                item_name=item_name,
                segments=[],
                status_prefix=status_prefix,
                detail_line=detail_line,
                item=item,
                state=None,
            )

        scope_id = self._scope_for_item(item) if item else None
        state = ObjectStateRegistry.get_by_scope(scope_id) if scope_id else None

        first_line_segments = self._format_segments(
            state,
            list(item_format.first_line),
            item_format.formatters,
        )
        preview_segments = self._format_segments(
            state,
            list(item_format.preview_line),
            item_format.formatters,
        )

        always_viewable = self._discover_always_viewable_fields(state)
        if always_viewable:
            logger.debug("PREVIEW: Adding always_viewable fields to preview: %s", always_viewable)
            always_viewable_segments = self._format_segments(
                state,
                list(always_viewable),
                item_format.formatters,
            )
            if preview_segments and always_viewable_segments:
                first_seg = always_viewable_segments[0]
                always_viewable_segments[0] = (first_seg[0], first_seg[1], " | ")
            preview_segments.extend(always_viewable_segments)

        if not detail_line and item_format.detail_line_field and state:
            detail_line = state.get_resolved_value(item_format.detail_line_field) or ""

        return self.build_multiline(
            item_name=item_name,
            segments=preview_segments,
            status_prefix=status_prefix,
            detail_line=detail_line,
            config_segments=None,
            first_line_segments=first_line_segments,
            item=item,
            state=state,
        )

    def build_multiline(
        self,
        *,
        item_name: str,
        segments: list[tuple[str, Optional[str]]],
        status_prefix: str = "",
        detail_line: str = "",
        config_segments: Optional[list[tuple[str, Optional[str]]]] = None,
        first_line_segments: Optional[list[tuple[str, Optional[str]]]] = None,
        item: Any = None,
        state: Any = None,
    ) -> StyledText:
        if item is not None and state is not None:
            self._append_signature_diff_segments(
                item=item,
                state=state,
                segments=segments,
                config_segments=config_segments,
                first_line_segments=first_line_segments,
            )

        layout = StyledTextLayout(
            name=Segment(text=item_name, field_path="", asterisk_prefix=True),
            status_prefix=status_prefix,
            first_line_segments=self._create_segments_with_grouping(first_line_segments or []),
            detail_line=detail_line,
            preview_segments=self._create_segments_with_grouping(
                segments,
                sep_before_first=" | ",
                asterisk_prefix=True,
            ),
            config_segments=self._create_segments_with_grouping(
                config_segments or [],
                sep_before_first=" | ",
                asterisk_prefix=True,
            ),
            multiline=True,
        )
        return StyledText(layout)

    def _append_signature_diff_segments(
        self,
        *,
        item: Any,
        state: Any,
        segments: list[tuple[str, Optional[str]]],
        config_segments: Optional[list[tuple[str, Optional[str]]]],
        first_line_segments: Optional[list[tuple[str, Optional[str]]]],
    ) -> None:
        sig_diff_fields = self._signature_diff_fields(item)
        existing_paths = {seg[1] for seg in segments if len(seg) > 1 and seg[1]}
        if config_segments:
            existing_paths.update(seg[1] for seg in config_segments if len(seg) > 1 and seg[1])
        if first_line_segments:
            existing_paths.update(seg[1] for seg in first_line_segments if len(seg) > 1 and seg[1])

        sig_diff_paths_to_add = [
            field_path
            for field_path in sig_diff_fields
            if field_path != "name"
            and not any(
                field_path == path or field_path.startswith(path + ".")
                for path in existing_paths
            )
        ]
        if not sig_diff_paths_to_add:
            return

        sig_diff_segments = self._preview_formatting_strategy.collect_and_render(
            state,
            sig_diff_paths_to_add,
            {},
            self._field_formatter,
        )
        if segments and sig_diff_segments:
            first_label, first_path, _ = sig_diff_segments[0]
            sig_diff_segments[0] = (first_label, first_path, " | ")
        segments.extend(sig_diff_segments)

    def _format_segments(
        self,
        state: Any,
        field_paths: list[str],
        formatters: dict[str, FieldFormatter],
    ) -> list[tuple[str, str, Optional[str]]]:
        return self._preview_formatting_strategy.collect_and_render(
            state,
            field_paths,
            formatters,
            self._field_formatter,
        )

    def _discover_always_viewable_fields(self, state: Any) -> set[str]:
        if state is None:
            return set()

        always_viewable = set()
        for path, config_type in state._path_to_type.items():
            if not is_dataclass(config_type):
                continue

            if is_enableable(config_type):
                enabled_path = f"{path}.{ENABLED_FIELD}" if path else ENABLED_FIELD
                resolved_enabled = state.get_resolved_value(enabled_path)
                if resolved_enabled is True:
                    always_viewable.add(enabled_path)
                    logger.debug(
                        "PREVIEW: Added enabled field %s for %s",
                        enabled_path,
                        config_type.__name__,
                    )

            registered_fields = self._registered_always_viewable_fields(config_type)
            if not registered_fields:
                continue

            if is_enableable(config_type):
                enabled_path = f"{path}.{ENABLED_FIELD}" if path else ENABLED_FIELD
                resolved_enabled = state.get_resolved_value(enabled_path)
                if resolved_enabled is not True:
                    logger.debug(
                        "PREVIEW: Skipping always_viewable fields for %s - enabled=%s",
                        config_type.__name__,
                        resolved_enabled,
                    )
                    continue

            for field_name in registered_fields:
                full_path = f"{path}.{field_name}" if path else field_name
                always_viewable.add(full_path)
                logger.debug(
                    "PREVIEW: Added always_viewable field %s for %s",
                    full_path,
                    config_type.__name__,
                )

        return always_viewable

    @staticmethod
    def _registered_always_viewable_fields(config_type: type) -> Optional[tuple[str, ...]]:
        if config_type in ALWAYS_VIEWABLE_FIELDS_REGISTRY:
            return ALWAYS_VIEWABLE_FIELDS_REGISTRY[config_type]
        for base in config_type.__mro__[1:]:
            if base in ALWAYS_VIEWABLE_FIELDS_REGISTRY:
                return ALWAYS_VIEWABLE_FIELDS_REGISTRY[base]
        return None

    @staticmethod
    def _create_segments_with_grouping(
        segments_list: list[tuple],
        sep_before_first: Optional[str] = None,
        asterisk_prefix: bool = False,
    ) -> list[Segment]:
        result = []
        for index, item in enumerate(segments_list):
            if len(item) == 2:
                label, path = item
                sep = None
            else:
                label, path, sep = item

            if sep is not None:
                sep_before = sep
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
