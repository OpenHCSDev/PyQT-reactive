"""Preview field formatting for manager list items."""

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from typing import Any, Optional


@dataclass(frozen=True)
class PreviewFieldFormatRequest:
    """Request to render one preview field value."""

    field_path: str
    value: Any

    @property
    def field_name(self) -> str:
        return self.field_path.split('.')[-1]


@dataclass(frozen=True)
class PreviewFieldFormatResult:
    """Typed optional carrier for preview text."""

    text: Optional[str]


class ManagerPreviewFieldFormatter:
    """Formats field values for AbstractManagerWidget preview segments."""

    def format_field(self, field_path: str, value: Any) -> Optional[str]:
        request = PreviewFieldFormatRequest(field_path=field_path, value=value)
        return self.resolve(request).text

    def resolve(self, request: PreviewFieldFormatRequest) -> PreviewFieldFormatResult:
        if request.value is None:
            return PreviewFieldFormatResult(text=None)

        abbrev = self._field_abbreviation(request.field_name, type(request.value))

        if is_dataclass(request.value) and not isinstance(request.value, type):
            return self._format_dataclass_value(request)

        formatted = self._format_preview_value(request.value)
        if formatted is None:
            return PreviewFieldFormatResult(text=None)
        return PreviewFieldFormatResult(text=f"{abbrev}:{formatted}")

    def _format_dataclass_value(
        self,
        request: PreviewFieldFormatRequest,
    ) -> PreviewFieldFormatResult:
        from pyqt_reactive.protocols import PreviewFormatterRegistry

        formatted = PreviewFormatterRegistry.format_field(request.value, request.field_name)
        if formatted is None:
            formatted = self._preview_label_for_config(request.value)
        return PreviewFieldFormatResult(text=formatted)

    def _format_preview_value(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, Enum):
            if value.value is None:
                return None
            return value.name
        if isinstance(value, list):
            if not value:
                return None
            if isinstance(value[0], Enum):
                return ",".join(v.value for v in value)
            return f"[{len(value)}]"
        if callable(value) and not isinstance(value, type):
            return getattr(value, "__name__", str(value))
        return str(value)

    def _preview_label_for_config(self, config_obj: Any) -> Optional[str]:
        from objectstate.lazy_factory import PREVIEW_LABEL_REGISTRY

        config_type = type(config_obj)
        if is_dataclass(config_obj):
            field_names = {field.name for field in fields(config_obj)}
            if "enabled" in field_names and not bool(getattr(config_obj, "enabled")):
                return None

        if config_type in PREVIEW_LABEL_REGISTRY:
            return PREVIEW_LABEL_REGISTRY[config_type]

        for base in config_type.__mro__[1:]:
            if base in PREVIEW_LABEL_REGISTRY:
                return PREVIEW_LABEL_REGISTRY[base]

        return None

    def _field_abbreviation(
        self,
        field_name: str,
        config_type: Optional[type] = None,
    ) -> str:
        from objectstate.lazy_factory import FIELD_ABBREVIATIONS_REGISTRY

        if config_type is not None:
            if config_type in FIELD_ABBREVIATIONS_REGISTRY:
                abbrevs = FIELD_ABBREVIATIONS_REGISTRY[config_type]
                if field_name in abbrevs:
                    return abbrevs[field_name]
            for base in config_type.__mro__[1:]:
                if base in FIELD_ABBREVIATIONS_REGISTRY:
                    abbrevs = FIELD_ABBREVIATIONS_REGISTRY[base]
                    if field_name in abbrevs:
                        return abbrevs[field_name]

        for abbrevs in FIELD_ABBREVIATIONS_REGISTRY.values():
            if field_name in abbrevs:
                return abbrevs[field_name]

        return field_name
