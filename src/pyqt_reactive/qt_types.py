"""Qt value types expressed directly through Python annotations."""

from __future__ import annotations

from typing import Annotated

from annotated_types import Predicate
from PyQt6.QtGui import QColor, QKeySequence


def is_valid_qt_color(value: str) -> bool:
    """Return whether Qt can construct a color from ``value``."""

    return QColor.isValidColor(value)


def is_valid_qt_key_sequence(value: str) -> bool:
    """Return whether ``value`` has a canonical portable key representation."""

    sequence = QKeySequence.fromString(
        value,
        QKeySequence.SequenceFormat.PortableText,
    )
    return not sequence.isEmpty() and bool(
        sequence.toString(QKeySequence.SequenceFormat.PortableText)
    )


QtColorText = Annotated[str, Predicate(is_valid_qt_color)]
QtKeySequenceText = Annotated[str, Predicate(is_valid_qt_key_sequence)]


__all__ = ("QtColorText", "QtKeySequenceText")
