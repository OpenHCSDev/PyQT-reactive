"""Reusable chrome for inline dataclass child-field sections."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from formbridge.forms.layout_constants import CURRENT_LAYOUT
from objectstate import DottedFieldPath
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pyqt_reactive.forms.inline_dataclass_context import (
    InlineDataclassChildFieldIdentity,
    InlineDataclassFormContext,
)
from pyqt_reactive.forms.widget_creation_config import (
    EnabledTitleWidgetMoveAuthority,
    ResetButtonStyler,
)
from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.shared.clickable_help_components import (
    HelpContext,
    LabelWithHelp,
)


class ChildFieldChrome(ABC):
    """Section headers and markers for the child fields of one dataclass editor.

    An editor is either a child of a form (its fields have ObjectState paths,
    help labels, reset buttons and dirty markers) or it stands alone. The two
    cases are the two members of this family, so an editor asks its chrome
    instead of testing whether it has a form.
    """

    __slots__ = ()

    @abstractmethod
    def add_section_header(
        self,
        layout: QVBoxLayout,
        group: QWidget,
        title: str,
        field_name: str,
    ) -> None:
        """Add the header of the section that edits ``field_name``."""

    @abstractmethod
    def navigation_target(self, field_name: str) -> QWidget | None:
        """The section widget a form scrolls to for ``field_name``, if it has one."""

    @abstractmethod
    def refresh_markers(self, field_names: Iterable[str] | None = None) -> None:
        """Redraw dirty, signature-diff, reset and inherited markers."""

    @abstractmethod
    def has_inherited_preview(self, field_name: str) -> bool:
        """Whether the form shows an inherited value for ``field_name``."""

    @abstractmethod
    def field_names_under(
        self,
        owner_field_paths: tuple[DottedFieldPath, ...],
    ) -> tuple[str, ...]:
        """The direct child fields of this editor among ObjectState paths."""

    @abstractmethod
    def child_paths(self, field_names: Iterable[str]) -> tuple[DottedFieldPath, ...]:
        """The ObjectState paths of child fields."""

    @abstractmethod
    def reset_child(self, field_name: str) -> None:
        """Reset one child field to its default."""

    @abstractmethod
    def reset_children(self) -> None:
        """Reset every child field to its default."""

    @abstractmethod
    def style_reset_button(self, button: QPushButton, field_name: str) -> None:
        """Style a reset button by whether ``field_name`` differs from its default."""

    @abstractmethod
    def provenance_button(self, field_name: str, color_scheme) -> QWidget | None:
        """A button that shows which scope supplied ``field_name``, if one exists."""

    @abstractmethod
    def emptied(self) -> ChildFieldChrome:
        """The same chrome with no sections registered, for a rebuilt editor."""

    @staticmethod
    def add_plain_header(layout: QVBoxLayout, group: QWidget, title: str) -> None:
        """Add a bold title with no field behind it."""

        label = QLabel(title, group)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(label)


@dataclass(slots=True)
class StandaloneChildChrome(ChildFieldChrome):
    """Chrome of an editor that is not a child of a form.

    There is no ObjectState behind the fields, so there are no paths, no dirty
    markers and no inherited values. Reset writes the dataclass default back
    through ``reset_field``, which the editor supplies.
    """

    reset_field: Callable[[str], None]

    def add_section_header(
        self,
        layout: QVBoxLayout,
        group: QWidget,
        title: str,
        field_name: str,
    ) -> None:
        self.add_plain_header(layout, group, title)

    def navigation_target(self, field_name: str) -> QWidget | None:
        return None

    def refresh_markers(self, field_names: Iterable[str] | None = None) -> None:
        return

    def has_inherited_preview(self, field_name: str) -> bool:
        return False

    def field_names_under(
        self,
        owner_field_paths: tuple[DottedFieldPath, ...],
    ) -> tuple[str, ...]:
        return ()

    def child_paths(self, field_names: Iterable[str]) -> tuple[DottedFieldPath, ...]:
        return ()

    def reset_child(self, field_name: str) -> None:
        self.reset_field(field_name)

    def reset_children(self) -> None:
        raise RuntimeError("Resetting every child field requires a form.")

    def style_reset_button(self, button: QPushButton, field_name: str) -> None:
        return

    def provenance_button(self, field_name: str, color_scheme) -> QWidget | None:
        return None

    def emptied(self) -> StandaloneChildChrome:
        return self


@dataclass(slots=True)
class InlineDataclassChildChrome(ChildFieldChrome):
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

    def add_section_header(
        self,
        layout: QVBoxLayout,
        group: QWidget,
        title: str,
        field_name: str,
    ) -> None:
        self.register_section_group(field_name, group)
        layout.addLayout(self.create_section_header(title=title, field_name=field_name))

    def navigation_target(self, field_name: str) -> QWidget | None:
        return self.groups.get(self.child_identity(field_name))

    def has_inherited_preview(self, field_name: str) -> bool:
        return self.context.child_has_inherited_preview(field_name)

    def field_names_under(
        self,
        owner_field_paths: tuple[DottedFieldPath, ...],
    ) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                path.field_name
                for path in owner_field_paths
                if path.value and path.parent == self.context.owner_path
            )
        )

    def child_paths(self, field_names: Iterable[str]) -> tuple[DottedFieldPath, ...]:
        return tuple(self.context.child_path(name) for name in field_names)

    def reset_child(self, field_name: str) -> None:
        self.context.reset_child(field_name)

    def reset_children(self) -> None:
        self.context.reset_children()

    def style_reset_button(self, button: QPushButton, field_name: str) -> None:
        self.context.update_reset_button_styling(button, field_name)

    def provenance_button(self, field_name: str, color_scheme) -> QWidget | None:
        return EnabledTitleWidgetMoveAuthority.create_title_provenance_button(
            state=self.context.state,
            dotted_path=self.context.child_path(field_name).value,
            color_scheme=color_scheme,
        )

    def emptied(self) -> InlineDataclassChildChrome:
        return InlineDataclassChildChrome(self.context)

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
