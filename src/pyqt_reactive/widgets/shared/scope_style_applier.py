"""Scope color scheme application helpers.

This module centralizes the logic for applying a ScopeColorScheme to an existing
widget subtree (help buttons/indicators + groupboxes).

No fallbacks: callers must pass a valid ScopeColorScheme.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from pyqt_reactive.widgets.shared.clickable_help_components import (
    GroupBoxWithHelp,
    HelpButton,
    HelpIndicator,
)
from pyqt_reactive.widgets.shared.scope_visual_config import ScopeColorScheme


def apply_scope_color_scheme_to_widget_tree(root: QWidget, scheme: ScopeColorScheme) -> None:
    """Apply scope styling to an existing widget tree."""

    if not scheme.step_border_layers:
        raise ValueError("ScopeColorScheme.step_border_layers must be non-empty")

    accent_color = scheme.accent_qcolor()

    for btn in root.findChildren(HelpButton):
        btn.set_scope_accent_color(accent_color)

    for indicator in root.findChildren(HelpIndicator):
        indicator.set_scope_accent_color(accent_color)

    for groupbox in root.findChildren(GroupBoxWithHelp):
        groupbox.set_scope_color_scheme(scheme)
