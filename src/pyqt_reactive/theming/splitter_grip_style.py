"""Cross-platform splitter grip rendering for the shared Qt theme."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QProxyStyle,
    QStyle,
    QStyleFactory,
    QStyleOption,
    QWidget,
)


class SplitterGripStyle(QProxyStyle):
    """Delegate platform styling while painting a consistent splitter grip."""

    _DOT_OFFSETS = (-6, -3, 0, 3, 6)
    _DOT_DIAMETER = 2

    def drawControl(
        self,
        element: QStyle.ControlElement,
        option: QStyleOption,
        painter: QPainter,
        widget: Optional[QWidget] = None,
    ) -> None:
        """Paint the native control, then overlay the palette-owned grip dots."""

        super().drawControl(element, option, painter, widget)
        if element != QStyle.ControlElement.CE_Splitter:
            return

        center = option.rect.center()
        dot_radius = self._DOT_DIAMETER // 2
        horizontal_layout = bool(
            option.state & QStyle.StateFlag.State_Horizontal
        )

        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(option.palette.color(QPalette.ColorRole.Mid))
        for offset in self._DOT_OFFSETS:
            if horizontal_layout:
                x = center.x() - dot_radius
                y = center.y() + offset - dot_radius
            else:
                x = center.x() + offset - dot_radius
                y = center.y() - dot_radius
            painter.drawEllipse(x, y, self._DOT_DIAMETER, self._DOT_DIAMETER)
        painter.restore()


_APPLICATION_STYLE_ATTRIBUTE = "_pyqt_reactive_splitter_grip_style"


def install_splitter_grip_style(app: QApplication) -> SplitterGripStyle:
    """Install one splitter painter owned by the supplied application."""

    if _APPLICATION_STYLE_ATTRIBUTE in app.__dict__:
        return app.__dict__[_APPLICATION_STYLE_ATTRIBUTE]

    style_key = app.style().objectName()
    base_style = QStyleFactory.create(style_key)
    if base_style is None:
        raise RuntimeError(
            f"Qt style factory cannot reproduce active style {style_key!r}."
        )
    splitter_style = SplitterGripStyle(base_style)
    app.setStyle(splitter_style)
    app.__dict__[_APPLICATION_STYLE_ATTRIBUTE] = splitter_style
    return splitter_style
