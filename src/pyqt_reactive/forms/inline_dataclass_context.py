"""Reusable ObjectState context for inline dataclass value widgets."""

from __future__ import annotations

from dataclasses import dataclass, fields as dataclass_fields
from typing import TYPE_CHECKING

from objectstate import DottedFieldPath
from objectstate.lazy_factory import get_base_type_for_lazy, replace_raw

if TYPE_CHECKING:
    from objectstate import ObjectState
    from PyQt6.QtGui import QColor
    from pyqt_reactive.forms.parameter_form_manager import ParameterFormManager
    from pyqt_reactive.forms.parameter_info_types import InlineDataclassWidgetInfo
    from pyqt_reactive.theming import ColorScheme


@dataclass(frozen=True, slots=True)
class InlineDataclassChildFieldIdentity:
    """Nominal ObjectState identity for one inline dataclass child field."""

    object_state_path: DottedFieldPath
    manager_path: DottedFieldPath
    owner_type: type

    @property
    def field_name(self) -> str:
        parts = self.object_state_path.parts
        if not parts:
            raise ValueError("Inline dataclass child field identity cannot be root.")
        return parts[-1]


@dataclass(frozen=True, slots=True)
class InlineDataclassFormContext:
    """ObjectState and chrome context for one inline dataclass value widget."""

    state: "ObjectState"
    manager: "ParameterFormManager"
    owner_path: DottedFieldPath
    local_owner_path: DottedFieldPath
    owner_type: type
    color_scheme: "ColorScheme | None"
    scope_accent_color: "QColor | None"

    @classmethod
    def from_inline_widget(
        cls,
        *,
        manager: "ParameterFormManager",
        param_info: "InlineDataclassWidgetInfo",
        current_value,
    ) -> "InlineDataclassFormContext":
        owner_path = (
            DottedFieldPath(manager.field_id).child(param_info.name)
            if manager.field_id
            else DottedFieldPath(param_info.name)
        )
        base_type = get_base_type_for_lazy(type(current_value)) or param_info.type
        return cls(
            state=manager.state,
            manager=manager,
            owner_path=owner_path,
            local_owner_path=DottedFieldPath(param_info.name),
            owner_type=base_type,
            color_scheme=manager.config.color_scheme,
            scope_accent_color=manager._scope_accent_color,
        )

    def child_identity(self, field_name: str) -> InlineDataclassChildFieldIdentity:
        return InlineDataclassChildFieldIdentity(
            object_state_path=self.owner_path.child(field_name),
            manager_path=self.local_owner_path.child(field_name),
            owner_type=self.owner_type,
        )

    def child_path(self, field_name: str) -> DottedFieldPath:
        return self.child_identity(field_name).object_state_path

    def child_manager_path(self, field_name: str) -> DottedFieldPath:
        return self.child_identity(field_name).manager_path

    def child_description(self, field_name: str) -> str | None:
        return self.state.parameter_descriptions.get(self.child_path(field_name).value)

    def child_type(self, field_name: str) -> type | None:
        for dataclass_field in dataclass_fields(self.owner_type):
            if dataclass_field.name == field_name:
                field_type = dataclass_field.type
                return field_type if isinstance(field_type, type) else None
        return None

    def raw_child_value(self, field_name: str):
        return self.state.parameters.get(self.child_path(field_name).value)

    def resolved_child_value(self, field_name: str):
        return self.state.get_resolved_value(self.child_path(field_name).value)

    def child_has_inherited_preview(self, field_name: str) -> bool:
        return (
            self.raw_child_value(field_name) is None
            and self.resolved_child_value(field_name) is not None
        )

    def reset_child(self, field_name: str) -> None:
        identity = self.child_identity(field_name)
        container_value = self.state.parameters[self.owner_path.value]
        default_value = self.state.signature_default(identity.object_state_path.value)
        if self.raw_child_value(field_name) == default_value:
            return
        self.manager.update_parameter(
            self.local_owner_path.value,
            replace_raw(container_value, **{field_name: default_value}),
        )

    def update_reset_button_styling(self, button, field_name: str) -> None:
        from pyqt_reactive.utils.styling_utils import update_reset_button_styling

        update_reset_button_styling(
            button,
            self.state,
            self.manager.field_id,
            self.child_manager_path(field_name).value,
        )
