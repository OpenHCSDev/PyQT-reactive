"""Structured styled-text layout for list item delegates."""

from dataclasses import dataclass, field
from typing import List, Optional

from PySide6.QtCore import QPointF
from PySide6.QtGui import QPainter, QPen, QColor


def join_segments(segments: List["Segment"], default_sep: str) -> str:
    """Join segments with separators, respecting per-segment sep_before overrides."""
    out: List[str] = []
    for index, segment in enumerate(segments):
        if index > 0:
            out.append(segment.sep_before if segment.sep_before is not None else default_sep)
        out.append(segment.text)
    return "".join(out)


@dataclass(frozen=True)
class Segment:
    """A styled text segment with field path for dirty/sig-diff matching."""

    text: str
    field_path: Optional[str] = None
    sep_before: Optional[str] = None
    asterisk_prefix: bool = False


@dataclass(frozen=True)
class ParagraphLineGuide:
    """A graphical hanging indent repeated for each laid-out visual line."""

    width_in_line_heights: float = 1.0
    points: tuple[tuple[float, float], ...] = ((0.22, 0.22), (0.22, 0.68), (0.78, 0.68))

    def width(self, line_height: float) -> float:
        return self.width_in_line_heights * line_height

    def paint(self, painter: QPainter, origin: QPointF, line_height: float, color: QColor) -> None:
        painter.save()
        painter.setPen(QPen(color, 1.0))
        points = tuple(origin + QPointF(x * line_height, y * line_height) for x, y in self.points)
        for start, end in zip(points, points[1:]):
            painter.drawLine(start, end)
        painter.restore()


@dataclass(frozen=True)
class StyledParagraph:
    """Semantic spans and optional graphical line decoration."""

    spans: tuple[tuple[Segment, bool], ...]
    line_guide: ParagraphLineGuide | None = None


@dataclass
class StyledTextLayout:
    """Structured layout for styled text rendering."""

    name: Segment
    status_prefix: str = ""
    first_line_segments: List[Segment] = field(default_factory=list)
    detail_line: str = ""
    preview_segments: List[Segment] = field(default_factory=list)
    config_segments: List[Segment] = field(default_factory=list)
    multiline: bool = False

    def display_paragraphs(self) -> list[StyledParagraph]:
        """Project display syntax once for both Qt painting and size calculation.

        The boolean marks primary (name/status) text; other spans use the
        preview color. Original segments retain their field-level styling.
        """
        title = [(Segment(self.status_prefix), True), (self.name, True)]
        inline = self.first_line_segments
        if not self.multiline and not inline:
            inline = self.preview_segments
        if inline:
            title += [(Segment("  ("), False)]
            title += self._separated_spans(inline, " | ")
            title += [(Segment(")"), False)]
        paragraphs = [StyledParagraph(tuple(title))]
        if not self.multiline:
            return paragraphs
        if self.detail_line:
            paragraphs.append(StyledParagraph(((Segment("  " + self.detail_line), False),)))
        if self.preview_segments or self.config_segments:
            preview = self._separated_spans(self.preview_segments, " | ")
            if self.preview_segments and self.config_segments:
                preview += [(Segment(" | "), False)]
            if self.config_segments:
                preview += [(Segment("configs=["), False)]
                preview += self._separated_spans(self.config_segments, ", ")
                preview += [(Segment("]"), False)]
            paragraphs.append(StyledParagraph(tuple(preview), ParagraphLineGuide()))
        return paragraphs

    @staticmethod
    def _separated_spans(segments: list[Segment], separator: str) -> list[tuple[Segment, bool]]:
        spans = []
        for index, segment in enumerate(segments):
            if index:
                spans.append(
                    (
                        Segment(separator if segment.sep_before is None else segment.sep_before),
                        False,
                    )
                )
            spans.append((segment, False))
        return spans

    def all_segments(self) -> List[Segment]:
        """Get all segments for dirty/sig-diff field set storage."""
        return [
            self.name,
            *self.first_line_segments,
            *self.preview_segments,
            *self.config_segments,
        ]

    def plain_text(self) -> str:
        """Return a compact plain-text representation for non-painted projections."""
        values: List[str] = []
        title = f"{self.status_prefix}{self.name.text}".strip()
        if title:
            values.append(title)

        first_line = join_segments(self.first_line_segments, " | ")
        if first_line:
            values.append(f"({first_line})")

        if self.detail_line:
            values.append(self.detail_line)

        preview = join_segments(self.preview_segments, " | ")
        if preview:
            values.append(preview)

        config = join_segments(self.config_segments, ", ")
        if config:
            values.append(f"configs=[{config}]")

        return " | ".join(values)


class StyledText(str):
    """String subclass carrying layout for per-field styling."""

    layout: Optional[StyledTextLayout]

    def __new__(cls, layout: StyledTextLayout):
        instance = super().__new__(cls, "")
        instance.layout = layout
        return instance

    @property
    def segments(self) -> List[tuple]:
        """Backwards compat: return segments as list of tuples."""
        if self.layout:
            return [(segment.text, segment.field_path) for segment in self.layout.all_segments()]
        return []
