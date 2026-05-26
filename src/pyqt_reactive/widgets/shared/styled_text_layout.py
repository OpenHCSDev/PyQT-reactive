"""Structured styled-text layout for list item delegates."""

from dataclasses import dataclass, field
from typing import List, Optional


def join_segments(segments: List["Segment"], default_sep: str) -> str:
    """Join segments with separators, respecting per-segment sep_before overrides."""
    out: List[str] = []
    for index, segment in enumerate(segments):
        if index > 0:
            out.append(
                segment.sep_before
                if segment.sep_before is not None
                else default_sep
            )
        out.append(segment.text)
    return "".join(out)


@dataclass(frozen=True)
class Segment:
    """A styled text segment with field path for dirty/sig-diff matching."""

    text: str
    field_path: Optional[str] = None
    sep_before: Optional[str] = None
    asterisk_prefix: bool = False


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

    def all_segments(self) -> List[Segment]:
        """Get all segments for dirty/sig-diff field set storage."""
        return [
            self.name,
            *self.first_line_segments,
            *self.preview_segments,
            *self.config_segments,
        ]


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
            return [
                (segment.text, segment.field_path)
                for segment in self.layout.all_segments()
            ]
        return []
