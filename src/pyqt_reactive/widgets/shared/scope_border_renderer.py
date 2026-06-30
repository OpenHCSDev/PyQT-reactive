"""Shared scope-border painting primitives."""

from __future__ import annotations

from PyQt6.QtCore import QRect, QRectF, Qt
from PyQt6.QtGui import QPainter, QPen
from PyQt6.QtWidgets import QWidget

from pyqt_reactive.widgets.shared.scope_visual_config import ScopeColorScheme


class ScopeBorderRenderer:
    """Paint scope border layers for widgets that receive a scope color scheme."""

    BORDER_PATTERNS = {
        "solid": (Qt.PenStyle.SolidLine, None),
        "dashed": (Qt.PenStyle.DashLine, [8, 6]),
        "dotted": (Qt.PenStyle.DotLine, [2, 6]),
        "dashdot": (Qt.PenStyle.DashDotLine, [8, 4, 2, 4]),
    }

    @classmethod
    def border_width(cls, scheme: ScopeColorScheme) -> int:
        """Return total reserved border width for a scope scheme."""

        return sum(layer[0] for layer in scheme.step_border_layers)

    @classmethod
    def paint_border_layers(
        cls,
        widget: QWidget,
        scheme: ScopeColorScheme,
        rect: QRect,
        *,
        radius: int = 0,
    ) -> None:
        """Paint all scope border layers into ``rect``."""

        if not scheme.step_border_layers:
            return

        painter = QPainter(widget)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        inset = 0
        for layer in scheme.step_border_layers:
            width, tint_index, pattern = (layer + ("solid",))[:3]
            del tint_index
            color = scheme.border_layer_qcolor(layer)
            pen = QPen(color, width)
            style, dash_pattern = cls.BORDER_PATTERNS.get(
                pattern,
                cls.BORDER_PATTERNS["solid"],
            )
            pen.setStyle(style)
            if dash_pattern:
                pen.setDashPattern(dash_pattern)

            offset = int(inset + width / 2)
            draw_rect = rect.adjusted(offset, offset, -offset - 1, -offset - 1)
            painter.setPen(pen)
            if radius:
                painter.drawRoundedRect(QRectF(draw_rect), radius, radius)
            else:
                painter.drawRect(draw_rect)
            inset += width

        painter.end()
