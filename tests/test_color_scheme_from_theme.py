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
    SelectedTabToneColour,
    SidebarToneColour,
    TIER_GAP,
)
from ui_theme.colour import Rgb

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
        "tab_bg": HeaderToneColour,
        "selected_tab_bg": SelectedTabToneColour,
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


# Chrome surfaces that touch on screen, so each pair must read as two surfaces.
TOUCHING = (
    ("window_bg", "panel_bg"), ("window_bg", "frame_bg"), ("panel_bg", "frame_bg"),
    ("panel_bg", "alternate_row_bg"), ("alternate_row_bg", "hover_bg"), ("tab_bg", "selected_tab_bg"),
)
# Areas secondary text is read on; a hover or the open tab holds the focused item in the foreground.
SURFACES = ("window_bg", "panel_bg", "frame_bg", "alternate_row_bg")


def rgb(triple: tuple[int, int, int]) -> Rgb:
    return Rgb(*triple)


@pytest.mark.parametrize("scheme", DRAWABLE, ids=lambda scheme: scheme.name)
def test_touching_chrome_surfaces_are_a_tier_apart_and_text_reads_on_each(scheme) -> None:
    chrome = ColorScheme.from_theme(scheme)
    for one, other in TOUCHING:
        gap = abs(rgb(getattr(chrome, one)).lightness - rgb(getattr(chrome, other)).lightness)
        assert gap >= TIER_GAP, (one, other, round(gap, 1))
    for surface in SURFACES:
        under = rgb(getattr(chrome, surface))
        primary = rgb(chrome.text_primary).contrast(under)
        assert rgb(chrome.text_secondary).contrast(under) >= min(4.5, primary), surface
