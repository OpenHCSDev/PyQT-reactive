"""Regression tests for contrast-aware dynamic accent chrome."""

from __future__ import annotations

from PyQt6.QtGui import QColor

from pyqt_reactive.theming import AccentChromeColorPolicy, ColorScheme, StyleSheetGenerator
from pyqt_reactive.widgets.shared.scope_color_utils import get_scope_color_scheme
from pyqt_reactive.widgets.shared.scoped_border_mixin import ScopedBorderMixin


class _ScopedBorderProbe(ScopedBorderMixin):
    """Expose the mixin's nominal stylesheet projections without a QWidget."""


def test_root_scope_accent_projects_readable_neutral_chrome() -> None:
    chrome = AccentChromeColorPolicy.resolve(get_scope_color_scheme("").accent_qcolor())

    assert chrome.background == "#555555"
    assert chrome.hover == "#666666"
    assert chrome.pressed == "#444444"
    assert chrome.border == "1px solid #ffffff"
    assert chrome.text == "#ffffff"


def test_dark_scope_accent_retains_its_identity() -> None:
    accent = QColor("#1473aa")

    chrome = AccentChromeColorPolicy.resolve(accent)

    assert chrome.background == accent.name()
    assert chrome.border == "none"
    assert chrome.text == "#ffffff"


def test_color_scheme_owns_wcag_contrast_calculation() -> None:
    assert ColorScheme.validate_wcag_contrast((255, 255, 255), (20, 115, 170))
    assert not ColorScheme.validate_wcag_contrast((255, 255, 255), (255, 255, 255))


def test_style_generator_uses_shared_contrast_policy() -> None:
    stylesheet = StyleSheetGenerator(ColorScheme()).generate_scope_accent_button_style(
        QColor("white")
    )

    assert "background-color: #555555" in stylesheet
    assert "color: #ffffff" in stylesheet


def test_scope_tree_selection_uses_shared_contrast_policy() -> None:
    probe = _ScopedBorderProbe()
    probe._scope_color_scheme = get_scope_color_scheme("")

    stylesheet = probe.get_scope_tree_selection_stylesheet()

    assert "background-color: #555555" in stylesheet
    assert "color: #ffffff" in stylesheet
    assert "background-color: rgba(255, 255, 255, 76)" in stylesheet
