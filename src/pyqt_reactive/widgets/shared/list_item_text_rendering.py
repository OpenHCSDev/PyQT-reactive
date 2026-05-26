"""Structured text rendering and sizing for multiline list items."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Set

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter

from pyqt_reactive.widgets.shared.styled_text_layout import Segment, StyledTextLayout


def field_matches(path: Optional[str], field_set: Set[str]) -> bool:
    """Return whether a segment field path matches any styled field."""
    if path is None:
        return False
    if path == "":
        return bool(field_set)
    return path in field_set or any(field.startswith(path + ".") for field in field_set)


@dataclass(frozen=True)
class TextPaintContext:
    """Inputs shared by structured text painting helpers."""

    dirty_fields: Set[str]
    sig_diff_fields: Set[str]
    base_font: QFont
    name_color: QColor
    preview_color: QColor


@dataclass(frozen=True)
class StyledTextPaintRequest:
    """One structured text paint pass."""

    painter: QPainter
    layout: StyledTextLayout
    context: TextPaintContext
    x_start: int
    y_offset: int
    line_height: int


@dataclass(frozen=True)
class SegmentListPaintStyle:
    """Display syntax for a separated segment list."""

    default_separator: str
    prefix: str = ""
    suffix: str = ""


class SegmentListPaintStyleKey(Enum):
    """Named segment-list display styles."""

    PARENTHESIZED_INLINE = SegmentListPaintStyle(" | ", "  (", ")")
    PREVIEW = SegmentListPaintStyle(" | ")
    CONFIG = SegmentListPaintStyle(", ", "configs=[", "]")

    @property
    def style(self) -> SegmentListPaintStyle:
        return self.value


@dataclass(frozen=True)
class SegmentListPaintSpec:
    """Projection for one separated segment-list paint operation."""

    segments: list[Segment]
    style_key: SegmentListPaintStyleKey

    @property
    def style(self) -> SegmentListPaintStyle:
        return self.style_key.style


class StyledTextRenderer:
    """Paints StyledTextLayout values without string parsing."""

    def paint_layout(
        self,
        painter: QPainter,
        layout: StyledTextLayout,
        context: TextPaintContext,
        x_start: int,
        y_offset: int,
        line_height: int,
    ) -> None:
        """Paint from structured layout."""
        request = StyledTextPaintRequest(
            painter=painter,
            layout=layout,
            context=context,
            x_start=x_start,
            y_offset=y_offset,
            line_height=line_height,
        )
        self._paint_layout(request)

    def _paint_layout(self, request: StyledTextPaintRequest) -> None:
        layout = request.layout
        context = request.context
        painter = request.painter
        y_offset = request.y_offset

        x = request.x_start
        if layout.status_prefix:
            x = self.draw_plain(
                painter, x, y_offset, layout.status_prefix, context.base_font, context.name_color
            )

        x = self.draw_plain(painter, x, y_offset, "▶ ", context.base_font, context.name_color)
        x = self.draw_segment(painter, x, y_offset, layout.name, context, context.name_color)

        if layout.first_line_segments:
            x = self._paint_segment_list(
                painter,
                context,
                spec=SegmentListPaintSpec(
                    layout.first_line_segments,
                    SegmentListPaintStyleKey.PARENTHESIZED_INLINE,
                ),
                x=x,
                y=y_offset,
            )

        if not layout.multiline:
            if layout.preview_segments and not layout.first_line_segments:
                self._paint_segment_list(
                    painter,
                    context,
                    spec=SegmentListPaintSpec(
                        layout.preview_segments,
                        SegmentListPaintStyleKey.PARENTHESIZED_INLINE,
                    ),
                    x=x,
                    y=y_offset,
                )
            return

        self._paint_multiline_preview(request)

    def _paint_multiline_preview(
        self,
        request: StyledTextPaintRequest,
    ) -> None:
        painter = request.painter
        layout = request.layout
        context = request.context
        x_start = request.x_start
        y = request.y_offset + request.line_height

        if layout.detail_line:
            self.draw_plain(
                painter, x_start, y, f"  {layout.detail_line}", context.base_font, context.preview_color
            )
            y += request.line_height

        if not layout.preview_segments and not layout.config_segments:
            return

        x = self.draw_plain(painter, x_start, y, "  └─ ", context.base_font, context.preview_color)
        x = self._paint_segment_list(
            painter,
            context,
            spec=SegmentListPaintSpec(
                layout.preview_segments,
                SegmentListPaintStyleKey.PREVIEW,
            ),
            x=x,
            y=y,
        )

        if layout.preview_segments and layout.config_segments:
            x = self.draw_plain(painter, x, y, " | ", context.base_font, context.preview_color)

        if layout.config_segments:
            self._paint_segment_list(
                painter,
                context,
                spec=SegmentListPaintSpec(
                    layout.config_segments,
                    SegmentListPaintStyleKey.CONFIG,
                ),
                x=x,
                y=y,
            )

    def _paint_segment_list(
        self,
        painter: QPainter,
        context: TextPaintContext,
        *,
        spec: SegmentListPaintSpec,
        x: int,
        y: int,
    ) -> int:
        style = spec.style
        if style.prefix:
            x = self.draw_plain(
                painter, x, y, style.prefix, context.base_font, context.preview_color
            )
        for index, segment in enumerate(spec.segments):
            if index > 0:
                separator = (
                    segment.sep_before
                    if segment.sep_before is not None
                    else style.default_separator
                )
                x = self.draw_plain(painter, x, y, separator, context.base_font, context.preview_color)
            x = self.draw_segment(painter, x, y, segment, context, context.preview_color)
        if style.suffix:
            x = self.draw_plain(
                painter, x, y, style.suffix, context.base_font, context.preview_color
            )
        return x

    def draw_segment(
        self,
        painter: QPainter,
        x: int,
        y: int,
        segment: Segment,
        context: TextPaintContext,
        color: QColor,
    ) -> int:
        """Draw a segment with dirty/sig-diff styling. Returns new x position."""
        is_dirty = field_matches(segment.field_path, context.dirty_fields)
        has_sig_diff = field_matches(segment.field_path, context.sig_diff_fields)

        if is_dirty and segment.asterisk_prefix:
            painter.setFont(context.base_font)
            painter.setPen(color)
            painter.drawText(x, y, "*")
            x += QFontMetrics(context.base_font).horizontalAdvance("*")

        font = QFont(context.base_font)
        font.setUnderline(has_sig_diff)
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(x, y, segment.text)
        x += QFontMetrics(font).horizontalAdvance(segment.text)

        if is_dirty and not segment.asterisk_prefix:
            painter.setFont(context.base_font)
            painter.setPen(color)
            painter.drawText(x, y, "*")
            x += QFontMetrics(context.base_font).horizontalAdvance("*")

        return x

    def draw_plain(
        self,
        painter: QPainter,
        x: int,
        y: int,
        text: str,
        font: QFont,
        color: QColor,
    ) -> int:
        """Draw plain text without styling. Returns new x position."""
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(x, y, text)
        return x + QFontMetrics(font).horizontalAdvance(text)


class StyledTextSizeCalculator:
    """Calculates size hints for structured and plain list-item text."""

    def from_layout(self, layout: StyledTextLayout, font: QFont) -> QSize:
        fm = QFontMetrics(font)
        line_count = 1
        if layout.detail_line:
            line_count += 1
        if layout.preview_segments or layout.config_segments:
            line_count += 1

        base_height = 25
        additional_height = 18
        total_height = base_height if line_count == 1 else base_height + additional_height * (line_count - 1)
        total_height += 4

        max_width = self._first_line_width(layout, fm)
        if layout.detail_line:
            max_width = max(max_width, fm.horizontalAdvance("  " + layout.detail_line))
        if layout.preview_segments or layout.config_segments:
            max_width = max(max_width, self._preview_line_width(layout, fm))

        return QSize(max_width + 20, total_height)

    def from_text(self, text: str, font: QFont) -> QSize:
        text = text.replace("\u2028", "\n")
        lines = text.split("\n")
        fm = QFontMetrics(font)
        base_height = 25
        additional_height = 18
        total_height = base_height if len(lines) == 1 else base_height + additional_height * (len(lines) - 1)
        total_height += 4
        max_width = max((fm.horizontalAdvance(line) for line in lines), default=0)
        return QSize(max_width + 20, total_height)

    def _first_line_width(self, layout: StyledTextLayout, fm: QFontMetrics) -> int:
        width = fm.horizontalAdvance(layout.name.text)
        if layout.status_prefix:
            width += fm.horizontalAdvance(layout.status_prefix)
        for segment in layout.first_line_segments:
            width += fm.horizontalAdvance(segment.text) + fm.horizontalAdvance(" | ")
        return width

    def _preview_line_width(self, layout: StyledTextLayout, fm: QFontMetrics) -> int:
        width = fm.horizontalAdvance("  └─ ")
        for segment in layout.preview_segments:
            width += fm.horizontalAdvance(segment.text) + fm.horizontalAdvance(", ")
        if layout.config_segments:
            if layout.preview_segments:
                width += fm.horizontalAdvance(" | ")
            joined_config = ", ".join(segment.text for segment in layout.config_segments)
            width += fm.horizontalAdvance(f"configs=[{joined_config}]")
        return width
