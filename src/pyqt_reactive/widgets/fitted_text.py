"""Text that fits whatever width its layout gives it.

A QLabel will not go narrower than its longest unbreakable run of text, so one long line (a
list of active teammates, a URL in an error, a thread status) set a minimum width on every
ancestor up to the window, and on a phone the window then ran past the screen. FittedText
asks for its text's width but needs only its margins; each member decides how text that
does not fit is shown, and the whole text stays the tooltip."""

import math

from PySide6.QtCore import QEvent, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QTextLayout, QTextOption
from PySide6.QtWidgets import QLabel


class FittedText(QLabel):
    """Text that takes the width it is given; members draw what does not fit."""

    WRAP_MODE = QTextOption.WrapMode.NoWrap
    ALIGN_VCENTER = int(Qt.AlignmentFlag.AlignVCenter)
    ALIGN_BOTTOM = int(Qt.AlignmentFlag.AlignBottom)

    RECOLORS_ON = frozenset({
        QEvent.Type.PaletteChange,
        QEvent.Type.StyleChange,
        QEvent.Type.EnabledChange,
        QEvent.Type.ApplicationPaletteChange,
    })
    REMEASURES_ON = frozenset({
        QEvent.Type.FontChange,
        QEvent.Type.StyleChange,
        QEvent.Type.ApplicationFontChange,
        QEvent.Type.ContentsRectChange,
        QEvent.Type.DevicePixelRatioChange,
    })

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._alignment_flags = int(self.alignment())
        self._text_color: QColor | None = None
        self._min_size_hint: QSize | None = None
        self._text_layouts: tuple[QRect, tuple[QTextLayout, ...], QPointF, bool] | None = None
        self.setText(text)

    def _clear_metrics_cache(self) -> None:
        self._min_size_hint = None
        self._text_layouts = None

    def setAlignment(self, alignment) -> None:  # noqa: N802 - Qt method name
        super().setAlignment(alignment)
        self._alignment_flags = int(alignment)
        self._text_layouts = None

    def setText(self, text: str) -> None:  # noqa: N802 - Qt method name
        if text == self.text():
            return
        self._clear_metrics_cache()
        super().setText(text)
        self.setToolTip(text)
        self.updateGeometry()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt virtual method name
        event_type = event.type()
        if event_type in self.RECOLORS_ON:
            self._text_color = None
        if event_type in self.REMEASURES_ON:
            self._clear_metrics_cache()
        super().changeEvent(event)

    def drawn(self, rect: QRect) -> tuple[int, str]:
        """The text flags and the text painted into this rectangle."""
        raise NotImplementedError

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method name
        cached = self._min_size_hint
        if cached is not None:
            return QSize(cached)
        margins = self.contentsMargins()
        hint = QSize(margins.left() + margins.right(),
                     self.fontMetrics().height() + margins.top() + margins.bottom())
        self._min_size_hint = hint
        return QSize(hint)

    def _layout_text(self, text: str, width: int) -> tuple[tuple[QTextLayout, ...], float]:
        """Lay out `text` into `width` pixels with the single QTextLayout engine used for both
        painting and wrapped height measurement."""
        font = self.font()
        option = QTextOption(self.alignment())
        option.setWrapMode(self.WRAP_MODE)
        layouts: list[QTextLayout] = []
        y = 0.0
        for paragraph in text.split("\n"):
            layout = QTextLayout(paragraph, font)
            layout.setCacheEnabled(True)
            layout.setTextOption(option)
            layout.beginLayout()
            while True:
                line = layout.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(width)
                line.setPosition(QPointF(0.0, y))
                y += line.height()
            layout.endLayout()
            layouts.append(layout)
        return tuple(layouts), y

    def _prepare_text_layouts(self, rect: QRect) -> tuple[QRect, tuple[QTextLayout, ...], QPointF, bool]:
        flags, text = self.drawn(rect)
        if not text or rect.width() <= 0 or rect.height() <= 0:
            cached = (QRect(rect), (), QPointF(), False)
            self._text_layouts = cached
            return cached
        layouts, y = self._layout_text(text, rect.width())
        if flags & self.ALIGN_VCENTER:
            top = rect.top() + (rect.height() - y) / 2.0
        elif flags & self.ALIGN_BOTTOM:
            top = rect.bottom() + 1.0 - y
        else:
            top = float(rect.top())
        needs_clip = y > rect.height() or rect != self.rect()
        cached = (QRect(rect), layouts, QPointF(float(rect.left()), top), needs_clip)
        self._text_layouts = cached
        return cached

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt virtual method name
        rect = self.contentsRect()
        cached = self._text_layouts
        if cached is None or cached[0] != rect:
            cached = self._prepare_text_layouts(rect)
        layouts = cached[1]
        if not layouts:
            return
        color = self._text_color
        if color is None:
            color = self._text_color = self.palette().color(QPalette.ColorRole.WindowText)
        painter = QPainter(self)
        if cached[3]:
            painter.setClipRect(rect)
        painter.setPen(color)
        origin = cached[2]
        for layout in layouts:
            layout.draw(painter, origin)


class ElidedLine(FittedText):
    """One line; what does not fit ends in an ellipsis."""

    def __init__(self, text: str = "") -> None:
        self._elided: tuple[int, str] | None = None
        super().__init__(text)
        self.setWordWrap(False)

    def _clear_metrics_cache(self) -> None:
        self._elided = None
        super()._clear_metrics_cache()

    def drawn(self, rect: QRect) -> tuple[int, str]:
        width = rect.width()
        cached = self._elided
        if cached is not None and cached[0] == width:
            return self._alignment_flags, cached[1]
        elided = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, width)
        self._elided = (width, elided)
        return self._alignment_flags, elided


class WrappedText(FittedText):
    """Lines that wrap at words, breaking a word only when it alone is wider than the line,
    and as tall as the wrapped text needs at the width given."""

    WRAP = Qt.TextFlag.TextWordWrap | Qt.TextFlag.TextWrapAnywhere
    WRAP_FLAGS = int(WRAP)
    WRAP_MODE = QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere

    def __init__(self, text: str = "") -> None:
        self._height_for_width: tuple[int, int] | None = None
        self._size_hint: QSize | None = None
        super().__init__(text)
        self.setWordWrap(True)

    def _clear_metrics_cache(self) -> None:
        self._height_for_width = None
        self._size_hint = None
        super()._clear_metrics_cache()

    def text_rect(self, width: int) -> QRect:
        margins = self.contentsMargins()
        inner = max(width - margins.left() - margins.right(), 1)
        _, y = self._layout_text(self.text(), inner)
        return QRect(0, 0, inner, math.ceil(y))

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt virtual method name
        cached = self._height_for_width
        if cached is not None and cached[0] == width:
            return cached[1]
        margins = self.contentsMargins()
        height = self.text_rect(width).height() + margins.top() + margins.bottom()
        self._height_for_width = (width, height)
        return height

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method name
        cached = self._size_hint
        if cached is not None:
            return QSize(cached)
        margins = self.contentsMargins()
        width = self.fontMetrics().boundingRect(QRect(0, 0, 1 << 20, 1 << 20), 0, self.text()).width()
        width += margins.left() + margins.right()
        hint = QSize(width, self.heightForWidth(width))
        self._size_hint = hint
        return QSize(hint)

    def drawn(self, rect: QRect) -> tuple[int, str]:
        return self._alignment_flags | self.WRAP_FLAGS, self.text()
