"""Reusable chrome for inline dataclass child-field sections."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from pyqt_reactive.forms.inline_dataclass_context import (
    InlineDataclassChildFieldIdentity,
    InlineDataclassFormContext,
)
from pyqt_reactive.forms.layout_constants import CURRENT_LAYOUT
from pyqt_reactive.forms.widget_creation_config import ResetButtonStyler
from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.shared.clickable_help_components import (
    HelpContext,
    LabelWithHelp,
)


@dataclass(slots=True)
class InlineDataclassChildChrome:
    """Own labels, reset controls, and navigation targets for inline children."""

    context: InlineDataclassFormContext
    labels: dict[InlineDataclassChildFieldIdentity, LabelWithHelp] = field(
        default_factory=dict
    )
    groups: dict[InlineDataclassChildFieldIdentity, QWidget] = field(
        default_factory=dict
    )
    reset_buttons: dict[InlineDataclassChildFieldIdentity, QPushButton] = field(
        default_factory=dict
    )

    def child_identity(self, field_name: str) -> InlineDataclassChildFieldIdentity:
        return self.context.child_identity(field_name)

    def register_section_group(self, field_name: str, group: QWidget) -> None:
        self.groups[self.child_identity(field_name)] = group

    def create_section_header(
        self,
        *,
        title: str,
        field_name: str,
    ) -> QHBoxLayout:
        identity = self.child_identity(field_name)
        label = self.create_label(title=title, identity=identity)
        reset_button = self.create_reset_button(identity)
        self.labels[identity] = label
        self.reset_buttons[identity] = reset_button

        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(3)
        title_layout.addWidget(
            label,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        title_layout.addStretch(1)
        title_layout.addWidget(reset_button)
        return title_layout

    def create_label(
        self,
        *,
        title: str,
        identity: InlineDataclassChildFieldIdentity,
    ) -> LabelWithHelp:
        label = LabelWithHelp(
            title,
            HelpContext(
                help_target=self.context.owner_type,
                param_name=identity.field_name,
                param_description=self.context.child_description(identity.field_name),
                param_type=self.context.child_type(identity.field_name),
                color_scheme=self.context.color_scheme,
                scope_accent_color=self.context.scope_accent_color,
            ),
            state=self.context.state,
            dotted_path=identity.object_state_path.value,
        )
        label.set_bold(True)
        label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        return label

    def create_reset_button(
        self,
        identity: InlineDataclassChildFieldIdentity,
    ) -> QPushButton:
        button = QPushButton("Reset")
        button.setMaximumWidth(60)
        button.setFixedHeight(min(CURRENT_LAYOUT.button_height, 24))
        button.setToolTip(f"Reset {identity.field_name} to default")
        ResetButtonStyler.apply(button, self.context.color_scheme or ColorScheme())
        button.clicked.connect(lambda: self.context.reset_child(identity.field_name))
        self.context.update_reset_button_styling(button, identity.field_name)
        return button

    def navigation_target(self, field_name: str) -> QWidget | None:
        return self.groups.get(self.child_identity(field_name))

    def refresh_markers(self, field_names: Iterable[str] | None = None) -> None:
        target_identities = self._target_identities(field_names)

        for identity in target_identities:
            label = self.labels.get(identity)
            if label is None:
                continue
            field_path = identity.object_state_path
            label.set_dirty_indicator(
                field_path.contains_any(self.context.state.dirty_fields)
            )
            label.set_underline(
                field_path.contains_any(self.context.state.signature_diff_fields)
            )

        for identity in target_identities:
            button = self.reset_buttons.get(identity)
            if button is None:
                continue
            self.context.update_reset_button_styling(button, identity.field_name)

        for identity in target_identities:
            group = self.groups.get(identity)
            if group is None:
                continue
            self.set_widget_dimmed(
                group,
                self.context.child_has_inherited_preview(identity.field_name),
                0.72,
            )

    def _target_identities(
        self,
        field_names: Iterable[str] | None,
    ) -> tuple[InlineDataclassChildFieldIdentity, ...]:
        if field_names is None:
            return tuple(self.labels) + tuple(
                identity
                for identity in self.groups
                if identity not in self.labels
            ) + tuple(
                identity
                for identity in self.reset_buttons
                if identity not in self.labels and identity not in self.groups
            )
        return tuple(self.child_identity(field_name) for field_name in field_names)

    @staticmethod
    def set_widget_dimmed(
        widget: QWidget,
        dimmed: bool,
        opacity: float = 0.4,
    ) -> None:
        state_property = "inline_dataclass_dimmed"
        opacity_property = "inline_dataclass_dimmed_opacity"
        if (
            widget.property(state_property) is dimmed
            and widget.property(opacity_property) == opacity
        ):
            return
        widget.setProperty(state_property, dimmed)
        widget.setProperty(opacity_property, opacity)
        if dimmed:
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(opacity)
            widget.setGraphicsEffect(effect)
        else:
            widget.setGraphicsEffect(None)
        widget.update()
