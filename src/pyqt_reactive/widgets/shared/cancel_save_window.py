"""A managed window whose header carries its title, Cancel and Save."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import ClassVar

from formbridge.forms.layout_constants import CURRENT_LAYOUT
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor, QShowEvent
from PyQt6.QtWidgets import QLabel, QPushButton

from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.shared.base_form_dialog import (
    BaseFormDialog,
    ManagedWindowActionCapabilities,
)
from pyqt_reactive.widgets.shared.form_window_action_header import (
    FormWindowActionHeader,
    HeaderAction,
    HeaderActionGroup,
    HeaderActionGroupRole,
)


class CancelSaveWindow(BaseFormDialog):
    """The shell every Cancel/Save editor window shares.

    It owns the header's commit group (Cancel rejects, Save calls the
    subclass's save), the widgets the dirty marker and the scope accent paint,
    the size the window takes the first time it is shown, and the agent-visible
    save and discard actions. A subclass says what goes beside the commit group
    and what the body is.
    """

    default_size: ClassVar[QSize]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._default_size_applied = False

    def build_cancel_save_header(
        self,
        color_scheme: ColorScheme,
        *,
        title_text: str,
        save_label: str,
        save_callback: Callable[[], None],
        other_groups: Sequence[HeaderActionGroup] = (),
    ) -> FormWindowActionHeader:
        """Build the header; every group in ``other_groups`` declares its role."""
        if self.size().isEmpty():
            self.resize(self.default_size)
        compact_style = color_scheme.styles.generate_config_button_styles()["compact"]

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = QPushButton(save_label)
        self.save_button.setEnabled(False)
        self.setup_save_button(self.save_button, save_callback)
        for button in (self.cancel_button, self.save_button):
            button.setFixedHeight(CURRENT_LAYOUT.button_height)
            button.setStyleSheet(compact_style)

        header = FormWindowActionHeader(
            title_text=title_text,
            title_color=color_scheme.to_hex(color_scheme.text_accent),
            action_groups=(
                *other_groups,
                HeaderActionGroup(
                    "group_commit",
                    (
                        HeaderAction("cancel", self.cancel_button),
                        HeaderAction("save", self.save_button),
                    ),
                    role=HeaderActionGroupRole.COMMIT,
                ),
            ),
            parent=self,
        )
        self.header_label: QLabel = header.header_label
        return header

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt virtual method name
        super().showEvent(event)
        if not self._default_size_applied:
            self.resize(self.default_size)
            self._default_size_applied = True
            self.setProperty("_fixed_default_size", True)

    def dirty_window_widgets(self) -> tuple[QLabel, QPushButton]:
        return self.header_label, self.save_button

    def managed_window_action_capabilities(self) -> ManagedWindowActionCapabilities:
        return ManagedWindowActionCapabilities(
            save_and_close=True,
            save_without_close=True,
            discard_and_close=True,
        )

    def apply_commit_accent(self, color_scheme: ColorScheme, accent_color: QColor) -> None:
        """Paint Save and the title in the window's scope accent."""
        self.save_button.setStyleSheet(
            color_scheme.styles.generate_scope_accent_button_style(accent_color)
        )
        self.header_label.setStyleSheet(f"color: {accent_color.name()};")
