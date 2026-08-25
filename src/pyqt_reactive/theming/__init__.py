"""
Theming and styling system.

Color schemes, palette management, and stylesheet generation
for consistent application-wide theming.
"""

from .accent_chrome import AccentChromeColorPolicy, AccentChromeColors
from .color_scheme import ColorScheme
from .color_scheme_resolution import ColorSchemeResolution, WidgetTheme
from .palette_manager import PaletteManager, ThemeManager
from .splitter_grip_style import ApplicationControlStyle
from .style_generator import StatusColorRole, StyleSheetGenerator

__all__ = [
    "AccentChromeColorPolicy",
    "AccentChromeColors",
    "ColorScheme",
    "ColorSchemeResolution",
    "WidgetTheme",
    "PaletteManager",
    "ThemeManager",
    "ApplicationControlStyle",
    "StatusColorRole",
    "StyleSheetGenerator",
]
