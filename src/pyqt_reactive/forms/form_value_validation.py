"""Semantic validation for writable values in a parameter-form tree."""

from __future__ import annotations

from objectstate import DottedFieldPath
from pyqt_reactive.protocols import CurrentValueValidatable


class FormValueValidationError(ValueError):
    """A writable form field contains an incomplete or invalid value."""


class FormValueValidationService:
    """Validate nominally capable widgets across one manager tree."""

    def validate_current_values(self, manager) -> None:
        self._validate_manager(manager)

    def _validate_manager(self, manager) -> None:
        for field_name, widget in manager.widgets.items():
            if not isinstance(widget, CurrentValueValidatable):
                continue
            try:
                widget.validate_current_value()
                manager._convert_widget_value(widget.get_value(), field_name)
            except ValueError as exc:
                field_path = DottedFieldPath(manager.field_id).child(field_name).value
                raise FormValueValidationError(
                    f"Invalid value for {field_path!r}: {exc}"
                ) from exc

        for nested_manager in manager.nested_managers.values():
            self._validate_manager(nested_manager)


FORM_VALUE_VALIDATION = FormValueValidationService()
