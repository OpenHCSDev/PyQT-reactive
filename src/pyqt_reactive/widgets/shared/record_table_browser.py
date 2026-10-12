"""A table of records whose columns are declared by its owner.

Each row is a mapping from column key to value. The owner declares the
columns (:class:`ColumnDef`) and, where a raw value has a human label, a
:class:`ValueLabelSource`; a labelled cell keeps the declaration that supplied
its label.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.shared.abstract_table_browser import (
    AbstractTableBrowser,
    ColumnDef,
    TableSelectionMode,
)

RecordValue = str | int | float | bool | None
RecordRow = Mapping[str, RecordValue]

MISSING_VALUE_TEXT = "N/A"


@dataclass(frozen=True, slots=True)
class LabelledValue:
    """One column value, its label, and the declaration that supplied the label."""

    column_key: str
    raw: str
    label: str | None = None
    source: object | None = None

    @property
    def text(self) -> str:
        """What the cell and the column filter show."""
        return self.raw if self.label is None else f"{self.raw} | {self.label}"


class ValueLabelSource(ABC):
    """Supplies the label of one raw column value."""

    @abstractmethod
    def labelled(self, column_key: str, raw: str) -> LabelledValue:
        """The value with its label and the label's source."""


class UnlabelledValues(ValueLabelSource):
    """Every value shows as written."""

    def labelled(self, column_key: str, raw: str) -> LabelledValue:
        return LabelledValue(column_key, raw)


class ValueLabels:
    """Remembers each labelled value, by raw value and by shown text."""

    def __init__(self, source: ValueLabelSource) -> None:
        self.source = source
        self._by_raw: dict[tuple[str, str], LabelledValue] = {}
        self._by_text: dict[tuple[str, str], LabelledValue] = {}

    def clear(self) -> None:
        """Forget every value; the source's labels may have changed."""
        self._by_raw.clear()
        self._by_text.clear()

    def labelled(self, column_key: str, raw: RecordValue) -> LabelledValue:
        """The labelled value for a present raw value."""
        key = (column_key, str(raw))
        if key not in self._by_raw:
            value = self.source.labelled(*key)
            self._by_raw[key] = value
            self._by_text[(column_key, value.text)] = value
        return self._by_raw[key]

    def text(self, column_key: str, raw: RecordValue) -> str:
        """What a cell shows; an absent value shows as ``N/A``."""
        if raw is None:
            return MISSING_VALUE_TEXT
        return self.labelled(column_key, raw).text

    def texts(self, column_key: str, raws: Iterable[RecordValue]) -> tuple[str, ...]:
        """What a set of raw values shows as."""
        return tuple(self.text(column_key, raw) for raw in raws)

    def shown(self, column_key: str, texts: Iterable[str]) -> tuple[LabelledValue, ...]:
        """The labelled values behind shown texts; unknown texts are skipped."""
        return tuple(
            self._by_text[(column_key, text)]
            for text in texts
            if (column_key, text) in self._by_text
        )


class RecordTableBrowser(AbstractTableBrowser[RecordRow]):
    """Multi-select table over mapping rows with owner-declared columns."""

    def __init__(
        self,
        color_scheme: ColorScheme | None = None,
        value_labels: ValueLabels | None = None,
        item_noun: str = AbstractTableBrowser.item_noun,
        parent=None,
    ):
        self._columns: tuple[ColumnDef, ...] = ()
        self.value_labels = (
            ValueLabels(UnlabelledValues()) if value_labels is None else value_labels
        )
        self.item_noun = item_noun
        super().__init__(
            color_scheme=color_scheme,
            selection_mode=TableSelectionMode.MULTI,
            parent=parent,
        )

    def set_columns(self, columns: Sequence[ColumnDef]) -> None:
        """Declare the columns. Call before ``set_items()``."""
        self._columns = tuple(columns)
        self.reconfigure_columns()

    def get_columns(self) -> list[ColumnDef]:
        return list(self._columns)

    def extract_row_data(self, item: RecordRow) -> list[str]:
        return [
            self.value_labels.text(column.key, item.get(column.key))
            for column in self._columns
        ]

    def get_searchable_text(self, item: RecordRow) -> str:
        return " ".join(
            str(item[column.key])
            for column in self._columns
            if item.get(column.key) is not None
        )

    def get_search_placeholder(self) -> str:
        return f"Search {self.item_noun}..."
