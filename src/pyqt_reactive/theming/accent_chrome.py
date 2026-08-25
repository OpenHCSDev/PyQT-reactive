"""Contrast-aware chrome projected from dynamic accent colours."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, TypeAlias

from PyQt6.QtGui import QColor

from .color_scheme import ColorScheme

AccentColor: TypeAlias = QColor | tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class AccentChromeColors:
    """Resolved stylesheet colours for one accent-backed control state set."""

    background: str
    hover: str
    pressed: str
    border: str
    text: str


class AccentChromeColorPolicy:
    """Project readable interactive chrome from a dynamic accent colour."""

    _MINIMUM_TEXT_CONTRAST: ClassVar[float] = 4.5
    _NEUTRAL_BACKGROUND: ClassVar[str] = "#555555"
    _NEUTRAL_HOVER: ClassVar[str] = "#666666"
    _NEUTRAL_PRESSED: ClassVar[str] = "#444444"
    _NEUTRAL_BORDER: ClassVar[str] = "1px solid #ffffff"
    _ACCENT_BORDER: ClassVar[str] = "none"
    _TEXT: ClassVar[str] = "#ffffff"

    @classmethod
    def resolve(cls, color: AccentColor) -> AccentChromeColors:
        """Return accent chrome whose white text meets WCAG AA contrast."""

        qcolor = cls._qcolor(color)
        if not ColorScheme.validate_wcag_contrast(
            (255, 255, 255),
            (qcolor.red(), qcolor.green(), qcolor.blue()),
            cls._MINIMUM_TEXT_CONTRAST,
        ):
            return AccentChromeColors(
                background=cls._NEUTRAL_BACKGROUND,
                hover=cls._NEUTRAL_HOVER,
                pressed=cls._NEUTRAL_PRESSED,
                border=cls._NEUTRAL_BORDER,
                text=cls._TEXT,
            )
        return AccentChromeColors(
            background=qcolor.name(),
            hover=qcolor.lighter(115).name(),
            pressed=qcolor.darker(115).name(),
            border=cls._ACCENT_BORDER,
            text=cls._TEXT,
        )

    @staticmethod
    def _qcolor(color: AccentColor) -> QColor:
        if isinstance(color, QColor):
            return QColor(color)
        return QColor(*color)
