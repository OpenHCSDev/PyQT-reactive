"""Color scheme resolution contracts for themed widgets."""

from __future__ import annotations

from dataclasses import dataclass

from pyqt_reactive.theming.color_scheme import ColorScheme


@dataclass(frozen=True, slots=True)
class ColorSchemeResolution:
    """Resolve an optional caller-provided color scheme into a concrete scheme."""

    provided_scheme: ColorScheme | None

    def resolve(self) -> ColorScheme:
        if self.provided_scheme is not None:
            return self.provided_scheme
        return ColorScheme()


@dataclass(frozen=True, slots=True)
class WidgetTheme:
    """Resolved color declaration for themed widgets."""

    scheme: ColorScheme

    @classmethod
    def from_optional(cls, provided_scheme: ColorScheme | None) -> "WidgetTheme":
        scheme = ColorSchemeResolution(provided_scheme).resolve()
        return cls(scheme=scheme)
