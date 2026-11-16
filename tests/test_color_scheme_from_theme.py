"""A ui_theme scheme projects onto the Qt chrome colours once, for every scheme Qt can draw."""

from __future__ import annotations

import pytest
from ui_theme.catalog import SCHEMES
from ui_theme.scheme import (
    AlternateRowToneColour,
    BackgroundColour,
    ErrorColour,
    ForegroundColour,
    HeaderToneColour,
    MutedColour,
    PrimaryColour,
    SidebarToneColour,
)

from pyqt_reactive.theming import ColorScheme

# A Qt window has no terminal, so a scheme drawn in the terminal's own colours is not one
# Qt can draw.
DRAWABLE = tuple(scheme for scheme in SCHEMES if not scheme.from_terminal)


@pytest.mark.parametrize("scheme", DRAWABLE, ids=lambda scheme: scheme.name)
def test_chrome_takes_the_theme_colours(scheme) -> None:
    chrome = ColorScheme.from_theme(scheme)
    stated = {
        "window_bg": BackgroundColour,
        "panel_bg": SidebarToneColour,
        "frame_bg": HeaderToneColour,
        "alternate_row_bg": AlternateRowToneColour,
        "text_primary": ForegroundColour,
        "text_secondary": MutedColour,
        "text_accent": PrimaryColour,
        "status_error": ErrorColour,
    }
    for field, member in stated.items():
        assert getattr(chrome, field) == member.rgb(scheme).triple, field
    preset = ColorScheme.create_dark_theme() if scheme.dark else ColorScheme.create_light_theme()
    assert chrome.python_keyword_color == preset.python_keyword_color
    assert f"alternate-background-color: {chrome.to_hex(chrome.alternate_row_bg)}" in (
        chrome.styles.generate_tree_widget_style())
