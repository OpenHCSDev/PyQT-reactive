"""Palette-owned checkbox rendering without replacing Qt's application style."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QPaintEvent, QPalette, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QStyle,
    QStyleOptionButton,
    QStyleOptionFocusRect,
)


def paint_themed_checkbox(
    checkbox: QCheckBox,
    option: QStyleOptionButton,
    painter: QPainter,
) -> None:
    """Paint one checkbox from its effective palette and native geometry."""

    style = checkbox.style()
    indicator = style.subElementRect(
        QStyle.SubElement.SE_CheckBoxIndicator,
        option,
        checkbox,
    ).adjusted(1, 1, -1, -1)
    enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
    group = QPalette.ColorGroup.Active if enabled else QPalette.ColorGroup.Disabled
    checked = bool(option.state & QStyle.StateFlag.State_On)
    partially_checked = bool(option.state & QStyle.StateFlag.State_NoChange)

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(option.palette.color(group, QPalette.ColorRole.Mid), 1))
    painter.setBrush(
        option.palette.color(
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
            option.palette.color(group, QPalette.ColorRole.ButtonText),
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
        painter.setBrush(option.palette.color(group, QPalette.ColorRole.ButtonText))
        painter.drawRect(indicator.adjusted(3, 3, -3, -3))
    painter.restore()

    style.drawControl(
        QStyle.ControlElement.CE_CheckBoxLabel,
        option,
        painter,
        checkbox,
    )
    if option.state & QStyle.StateFlag.State_HasFocus:
        focus_option = QStyleOptionFocusRect()
        focus_option.initFrom(checkbox)
        focus_option.rect = style.subElementRect(
            QStyle.SubElement.SE_CheckBoxFocusRect,
            option,
            checkbox,
        )
        focus_option.state = option.state
        focus_option.backgroundColor = option.palette.color(
            group,
            QPalette.ColorRole.Window,
        )
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_FrameFocusRect,
            focus_option,
            painter,
            checkbox,
        )


class ThemedCheckBox(QCheckBox):
    """Checkbox whose indicator derives from the active Qt palette."""

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        option = QStyleOptionButton()
        self.initStyleOption(option)
        painter = QPainter(self)
        paint_themed_checkbox(self, option, painter)
        painter.end()
