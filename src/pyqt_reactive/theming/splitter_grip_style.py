"""Cross-platform splitter grip rendering for the shared Qt theme."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QPalette, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QProxyStyle,
    QStyle,
    QStyleFactory,
    QStyleOption,
    QWidget,
)


class ApplicationControlStyle(QProxyStyle):
    """Delegate platform styling while painting palette-owned native controls."""

    _DOT_OFFSETS = (-6, -3, 0, 3, 6)
    _DOT_DIAMETER = 2

    def drawPrimitive(  # noqa: N802 - Qt virtual method name
        self,
        element: QStyle.PrimitiveElement,
        option: QStyleOption,
        painter: QPainter,
        widget: QWidget | None = None,
    ) -> None:
        """Paint check-box indicators from the active application palette."""

        if element != QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            super().drawPrimitive(element, option, painter, widget)
            return

        palette = option.palette
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        group = (
            QPalette.ColorGroup.Active
            if enabled
            else QPalette.ColorGroup.Disabled
        )
        checked = bool(option.state & QStyle.StateFlag.State_On)
        partially_checked = bool(option.state & QStyle.StateFlag.State_NoChange)
        indicator = option.rect.adjusted(1, 1, -1, -1)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(palette.color(group, QPalette.ColorRole.Mid), 1))
        painter.setBrush(
            palette.color(
                group,
                (
                    QPalette.ColorRole.Button
                    if checked or partially_checked
                    else QPalette.ColorRole.Base
                ),
            )
        )
        painter.drawRect(indicator)

        if checked:
            check_pen = QPen(
                palette.color(group, QPalette.ColorRole.ButtonText),
                max(1.5, indicator.width() / 8),
            )
            check_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            check_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(check_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(
                indicator.left() + indicator.width() * 2 // 9,
                indicator.center().y(),
                indicator.left() + indicator.width() * 4 // 9,
                indicator.bottom() - indicator.height() * 2 // 9,
            )
            painter.drawLine(
                indicator.left() + indicator.width() * 4 // 9,
                indicator.bottom() - indicator.height() * 2 // 9,
                indicator.right() - indicator.width() // 7,
                indicator.top() + indicator.height() // 4,
            )
        elif partially_checked:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(
                palette.color(group, QPalette.ColorRole.ButtonText)
            )
            painter.drawRect(indicator.adjusted(3, 3, -3, -3))
        painter.restore()

    def drawControl(  # noqa: N802 - Qt virtual method name
        self,
        element: QStyle.ControlElement,
        option: QStyleOption,
        painter: QPainter,
        widget: QWidget | None = None,
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


_APPLICATION_STYLE_ATTRIBUTE = "_pyqt_reactive_application_control_style"


def install_application_control_style(
    app: QApplication,
) -> ApplicationControlStyle:
    """Install one native-control painter owned by the supplied application."""

    if _APPLICATION_STYLE_ATTRIBUTE in app.__dict__:
        return app.__dict__[_APPLICATION_STYLE_ATTRIBUTE]

    style_key = app.style().objectName()
    base_style = QStyleFactory.create(style_key)
    if base_style is None:
        raise RuntimeError(
            f"Qt style factory cannot reproduce active style {style_key!r}."
        )
    application_style = ApplicationControlStyle(base_style)
    app.setStyle(application_style)
    app.__dict__[_APPLICATION_STYLE_ATTRIBUTE] = application_style
    return application_style
