"""Rows drawn as rich-text documents in a virtual list.

Each row is laid out once, in its final form, and a layout of the view lays out only the
rows near the reader: those within `MEASURED_VIEWPORTS` viewports of the reader's row. A row
further away stands in at a height estimated from its plain text's lines and is measured
later, nearest the reader first, a `MEASURE_SLICE_SECONDS` slice at a time between frames,
each slice laying the view out again with the reader held where they are. A row's expensive
formatting is prepared on the delegate's thread pool; until it arrives the row stands in
the same way and paints its text plain. Each row's document and height are cached by the
row, its font and the width it is laid out at. Preparations reach the GUI thread in batches
(when the pool's queue empties, and at most every `BATCH_SECONDS` while it works), and each
batch lays the view out once. A suspended application (Android, once the reader switches
away) lets its laid-out documents go.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import math
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Hashable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property

from PySide6.QtCore import (
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRect,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAbstractTextDocumentLayout,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QRegion,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)


class RowFormatting:
    """How one row's text is formatted in its document."""

    final = True
    """Whether this is the row's formatting to lay out, rather than a stand-in for it."""

    @abstractmethod
    def fill(self, document: QTextDocument) -> None: ...

    def resolved(self) -> RowFormatting:
        """The formatting this one fills with; a member that prepares on demand prepares here."""
        return self


@dataclass(frozen=True)
class PlainRow(RowFormatting):
    """A row whose formatting is not prepared yet paints its plain text."""

    text: str

    def fill(self, document: QTextDocument) -> None:
        document.setPlainText(self.text)


@dataclass(frozen=True)
class PendingRow(PlainRow):
    """A row whose formatting is still being prepared: it stands in at the height its plain
    text's lines take and paints that text plain, without a document laid out for it, so
    the row is laid out once, when its formatting arrives."""

    final = False

    def estimated_height(self, font: QFont, width: float) -> int:
        metrics = QFontMetrics(font)
        per_line = max(1, int(width // max(1, metrics.averageCharWidth())))
        lines = sum(max(1, math.ceil(len(line) / per_line)) for line in self.text.split("\n"))
        return lines * metrics.lineSpacing()


@dataclass(frozen=True)
class HtmlRow(RowFormatting):
    """A row drawn from rich text prepared for it."""

    html: str

    def fill(self, document: QTextDocument) -> None:
        document.setHtml(self.html)


class PreparedRowSignals(QObject):
    """Finished preparations: a batch of (key, formatting) pairs."""

    finished = Signal(object)


class PreparationQueue:
    """The rows waiting for their formatting, and whether a worker is draining them."""

    def __init__(self) -> None:
        self.waiting: deque[tuple[Hashable, Callable[[], RowFormatting]]] = deque()
        self.lock = threading.Lock()
        self.draining = False

    def add(self, key: Hashable, prepare: Callable[[], RowFormatting]) -> bool:
        """Queue a row; True when no worker is draining, so the caller starts one."""
        with self.lock:
            self.waiting.append((key, prepare))
            starting, self.draining = not self.draining, True
        return starting

    def next(self) -> tuple[Hashable, Callable[[], RowFormatting]] | None:
        with self.lock:
            if not self.waiting:
                self.draining = False
                return None
            return self.waiting.popleft()

    def clear(self) -> None:
        with self.lock:
            self.waiting.clear()


class RowPreparations(QRunnable):
    """Works out queued rows' formatting on the pool, one after another, and hands them to
    the GUI thread in batches: when the queue empties, and at most every `BATCH_SECONDS`
    while it is still working, so a page of rows arrives as one batch, not one at a time."""

    BATCH_SECONDS = 0.1

    def __init__(self, queue: PreparationQueue, signals: PreparedRowSignals) -> None:
        super().__init__()
        self.queue = queue
        self.signals = signals

    def run(self) -> None:
        batch: list[tuple[Hashable, RowFormatting]] = []
        started = time.monotonic()
        while (queued := self.queue.next()) is not None:
            key, prepare = queued
            batch.append((key, prepare()))
            if time.monotonic() - started >= self.BATCH_SECONDS:
                self.signals.finished.emit(batch)
                batch, started = [], time.monotonic()
        if batch:
            self.signals.finished.emit(batch)


class RowPreparer(ABC):
    """Where rows' formatting is worked out, away from the GUI thread. A delegate queues each
    row's work here and is told, on the GUI thread, of the batches that finish (`arrived`).

    Which member a delegate uses is its own (`RowDocumentDelegate.row_preparer`). The work
    is the member's too: `ThreadRowPreparer` calls it on a thread of this process, so Python
    work there takes turns with the GUI thread for the interpreter; a member that hands the
    work to another process needs it to be something that process can receive."""

    def __init__(self, arrived: Callable[[list[tuple[Hashable, RowFormatting]]], None]) -> None:
        self.arrived = arrived

    @abstractmethod
    def prepare(self, key: Hashable, work: Callable[[], RowFormatting]) -> None:
        """Work out the row's formatting; it arrives in a batch, under `key`."""

    @abstractmethod
    def clear(self) -> None:
        """Drop the rows queued and not started."""

    @abstractmethod
    def stop(self) -> None:
        """Join what is running: nothing arrives after this returns."""


class ThreadRowPreparer(RowPreparer):
    """One worker thread of this process, draining the queue in order."""

    def __init__(self, arrived: Callable[[list[tuple[Hashable, RowFormatting]]], None],
                 parent: QObject) -> None:
        super().__init__(arrived)
        # The thread and its signals share the delegate's lifetime.
        self.pool = QThreadPool(parent)
        self.pool.setMaxThreadCount(1)
        self.signals = PreparedRowSignals(self.pool)
        self.signals.finished.connect(arrived)
        self.queue = PreparationQueue()

    def prepare(self, key: Hashable, work: Callable[[], RowFormatting]) -> None:
        if self.queue.add(key, work):
            self.pool.start(RowPreparations(self.queue, self.signals))

    def clear(self) -> None:
        self.queue.clear()
        self.pool.clear()

    def stop(self) -> None:
        self.pool.waitForDone()


class DetachedRows:
    """Rows no view draws yet: nothing to lay out again or repaint, and no viewport width."""

    def rows_changed(self) -> None:
        """No view, so nothing to lay out again."""

    def rows_repainted(self) -> None:
        """No view, so nothing to repaint."""

    def viewport_width(self) -> int:
        return 0

    def estimating(self) -> bool:
        """No view lays rows out, so every row asked for is measured."""
        return False


class RowSize:
    """One model row's measured size at a layout's font and width, and the preparation key it
    was measured under, so the row's new formatting (`_row_prepared`) measures it against
    this and drops it when it differs."""

    __slots__ = ("key", "size", "font", "estimated")

    def __init__(self, key: Hashable, size: QSize | None, font: QFont, estimated: bool = False) -> None:
        # Its own copy: the font it was handed belongs to a style option Qt frees.
        self.key, self.size, self.font, self.estimated = key, size, QFont(font), estimated


class RowDocumentDelegate(QStyledItemDelegate):
    """Paints each row as a QTextDocument at the view's width.

    A member says what a row is keyed by, what its plain text is, how its formatting is
    prepared off the GUI thread and how a prepared formatting fills a document. Rows
    whose formatting is still being prepared paint their plain text.
    """

    MAX_PREPARED_ROWS = 10_000
    MAX_DOCUMENTS = 500
    ROW_PADDING = 4
    MEASURE_SLICE_SECONDS = 0.008
    """How long one slice of measuring the rows away from the reader may take."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.view: DetachedRows | VirtualRowView = DetachedRows()
        self.preparing = True
        self._stopped = False
        self._prepared: OrderedDict[Hashable, RowFormatting] = OrderedDict()
        self._pending: set[Hashable] = set()
        self._documents: OrderedDict[tuple[Hashable, int], QTextDocument] = OrderedDict()
        self._size_hints: dict[tuple[Hashable, int], QSize] = {}
        # A laid-out row wider than its layout width (unwrapped content): how wide, by the
        # same key the height is kept under.
        self._extents: dict[tuple[Hashable, int], int] = {}
        # The widths each key has a document or height cached at, so an arrival drops them.
        self._cached_widths: dict[Hashable, set[int]] = {}
        # A batch of finished preparations lays the view out once, in the next frame.
        self._viewport_update_timer = QTimer(self)
        self._viewport_update_timer.setSingleShot(True)
        self._viewport_update_timer.setInterval(16)
        self._viewport_update_timer.timeout.connect(self._update_viewport)
        # Each model row's measured size, aligned with the model's rows, at the font and width
        # they were measured for (`_row_sizes_for`). Qt's list layout asks every row's size
        # on each layout; while one runs (`_layout_for`), a row answers from here without
        # building a style option or a preparation key. The view keeps them aligned with the
        # model's inserts, removals and changes, so rows that arrive are the only ones measured.
        # A kept size answers without asking the row's preparation key again: a member whose
        # key for a row changes with no model signal (a look changed in place) emits the
        # model's dataChanged for that row, or calls forget_row_sizes when every key changes.
        self._row_sizes: list[RowSize | None] = []
        self._row_size_keys: dict[Hashable, list[RowSize]] = {}
        self._row_sizes_for: Hashable = None
        self._layout_for: Hashable = None
        # Rows a layout estimated, away from the reader: measured a slice at a time.
        self._unmeasured: dict[QPersistentModelIndex, None] = {}
        self._measure_timer = QTimer(self)
        self._measure_timer.setSingleShot(True)
        self._measure_timer.setInterval(0)
        self._measure_timer.timeout.connect(self._measure_slice)
        QGuiApplication.instance().applicationStateChanged.connect(self._application_state_changed)

    # What a member says about its rows

    def row_key(self, index: QModelIndex) -> Hashable:
        """What a row's document is cached under; the plain text by default."""
        return index.data(Qt.ItemDataRole.DisplayRole)

    def row_text(self, index: QModelIndex) -> str:
        return index.data(Qt.ItemDataRole.DisplayRole) or ""

    def preparation_key(self, index: QModelIndex, font: QFont, width: int) -> Hashable:
        """What a prepared formatting is cached under: the row and its font, at any width."""
        return self.row_key(index), font.family(), font.pointSize()

    @abstractmethod
    def preparation(self, index: QModelIndex, font: QFont, width: int) -> Callable[[], RowFormatting]:
        """The work that prepares this row's formatting on the pool."""

    def text_width(self, width: int) -> float:
        """Rows wrap at the width they are drawn at."""
        return width

    def paint_background(self, painter, option: QStyleOptionViewItem, row: int) -> None:
        """Rows draw no background of their own."""

    def stop_preparation(self) -> None:
        """Close whatever the preparations run through; the preparer itself is joined after."""

    @cached_property
    def preparer(self) -> RowPreparer:
        """Where this delegate's rows are prepared, made when the first row asks."""
        return self.row_preparer()

    def row_preparer(self) -> RowPreparer:
        """A worker thread of this process, unless a member prepares its rows elsewhere."""
        return ThreadRowPreparer(self._rows_prepared, self)

    # Caches

    def formatting(self, index: QModelIndex, font: QFont, width: int) -> RowFormatting:
        """The row's prepared formatting, or its plain text while that is being prepared."""
        return self.keyed_formatting(self.preparation_key(index, font, width), self.row_text(index),
                                     self.preparation(index, font, width))

    def keyed_formatting(self, key: Hashable, text: str, prepare: Callable[[], RowFormatting]) -> RowFormatting:
        """The formatting prepared under `key`, queueing `prepare` with the delegate's
        preparer the first time; a `PendingRow` stands in until it arrives."""
        if key in self._prepared:
            self._prepared.move_to_end(key)
            return self._prepared[key]
        if self.preparing and key not in self._pending:
            self._pending.add(key)
            self.preparer.prepare(key, prepare)
        return PendingRow(text)

    def final_document(self, index: QModelIndex, font: QFont, width: int) -> QTextDocument | None:
        """The row's document laid out in its final form, or None while its formatting is
        being prepared: a pending row is never laid out."""
        key = (self.preparation_key(index, font, width), width)
        document = self._documents.get(key)
        if document is not None:
            self._documents.move_to_end(key)
            return document
        formatting = self.formatting(index, font, width)
        if not formatting.final:
            return None
        return self.laid_out(key[0], font, width, formatting)

    def laid_out(
        self, key: Hashable, font: QFont, width: int, formatting: RowFormatting
    ) -> QTextDocument:
        """The document of a row's final formatting at `width`, laid out once and kept: the
        measurement that sizes the row and the paint that draws it read the same document.
        A measurement used to lay out a document of its own and drop it, so a row a member
        measured before drawing it (a pager sizing a page it is about to publish) was laid
        out twice."""
        cache_key = (key, width)
        document = self._documents.get(cache_key)
        if document is not None:
            self._documents.move_to_end(cache_key)
            return document
        document = self.new_document(font, width)
        formatting.fill(document)
        self._documents[cache_key] = document
        self._cached_widths.setdefault(key, set()).add(width)
        extent = max(math.ceil(document.idealWidth()), math.ceil(document.size().width()))
        if extent > width:
            self._extents[cache_key] = extent
        if len(self._documents) > self.MAX_DOCUMENTS:
            self._documents.popitem(last=False)
        return document

    def row_extent(self, key: Hashable, width: int) -> int:
        """How wide the row's content is when laid out at `width`: `width` itself where it
        wraps, more where it holds content that does not (a `pre` block). Recorded when the
        row is laid out and kept with its height, so asking it lays nothing out; a row not
        laid out yet answers `width`."""
        return self._extents.get((key, width), width)

    def row_document(self, index: QModelIndex, font: QFont, width: int) -> QTextDocument:
        """The row's document; a pending row's is its plain text, laid out for this one ask
        (a tap over it) and not kept."""
        document = self.final_document(index, font, width)
        if document is None:
            document = self.new_document(font, width)
            PlainRow(self.row_text(index)).fill(document)
        return document

    def new_document(self, font: QFont, width: int) -> QTextDocument:
        document = QTextDocument()
        # No margin: a row's text starts where the row does.
        document.setDocumentMargin(0)
        document.setDefaultFont(font)
        document.setTextWidth(self.text_width(width))
        return document

    def measured_height(self, key: Hashable, font: QFont, width: int, formatting: RowFormatting) -> int:
        """How tall `formatting` is at `width`, cached by (key, width).

        The row measurement sizeHint caches, offered to a caller that has a row's key and
        formatting but no model index — a pager summing the pixels its loaded rows take.
        The cache is shared with sizeHint, so a row is laid out into a document once per
        width however many times its height is asked for, and a row whose prepared
        formatting arrives drops its cached height the same frame its documents do.
        """
        cache_key = (key, width)
        size = self._size_hints.get(cache_key)
        if size is not None:
            return size.height()
        formatting = formatting.resolved()
        if not formatting.final:
            return formatting.estimated_height(font, self.text_width(width)) + self.ROW_PADDING
        document = self.laid_out(key, font, width, formatting)
        size = self._size_hints[cache_key] = QSize(width, int(document.size().height()) + self.ROW_PADDING)
        return size.height()

    def _rows_prepared(self, batch: list[tuple[Hashable, RowFormatting]]) -> None:
        """A batch of rows' formatting arrived; each lands as `_row_prepared`, and the view
        lays out once for the batch, in the next frame."""
        if self._stopped:
            return
        for key, prepared in batch:
            self._row_prepared(key, prepared)

    def _row_prepared(self, key: Hashable, prepared: RowFormatting) -> None:
        """One row's formatting arrived (from the pool, or adopted by a member): it is what
        the row lays out from now on. A pending row cached nothing; what a member drew under
        the key meanwhile (a look it showed before) is dropped, so the row lays out once,
        from this. In the next frame, once however many arrive, the view lays out again if
        a row changed height (`_moves_rows`), and otherwise repaints."""
        if self._stopped:
            return
        awaited = key in self._pending
        self._pending.discard(key)
        self._prepared[key] = prepared
        if len(self._prepared) > self.MAX_PREPARED_ROWS:
            self._prepared.popitem(last=False)
        for width in self._cached_widths.pop(key, ()):
            self._documents.pop((key, width), None)
            self._size_hints.pop((key, width), None)
            self._extents.pop((key, width), None)
        if self._moves_rows(key, prepared, awaited):
            self._arrivals_moved_rows = True
        if not self._viewport_update_timer.isActive():
            self._viewport_update_timer.start()

    def _moves_rows(self, key: Hashable, prepared: RowFormatting, awaited: bool) -> bool:
        """Whether the formatting that arrived under `key` changes a drawn row's height.

        - A row measured under the key (from the look a member drew meanwhile) that is as
          tall from what arrived keeps its size; one that differs, or was an estimate, is
          measured by the layout its arrival asks for.
        - A row that was waiting for the key with no measured size drew its plain text at an
          estimate nothing kept: its arrival lays it out.
        - Formatting no row was waiting for (a member prepared it before drawing the row,
          `adopt`) changes no drawn row.

        Every arrival used to lay every row out. Scrolling ten pages back in a Toad history
        ran 97 whole layouts: 422 arrivals were rows prepared before they were drawn, and
        109 were new looks of a row at the height it had (a sent message's receipt).
        """
        kept_sizes = self._row_size_keys.pop(key, ())
        moves = awaited and not kept_sizes
        for kept in kept_sizes:
            size = kept.size
            if size is None:
                continue
            if kept.estimated or self.measured_height(key, kept.font, size.width(), prepared) != size.height():
                kept.size = None
                moves = True
            else:
                self._row_size_keys.setdefault(key, []).append(kept)
        return moves

    _arrivals_moved_rows = False

    def _update_viewport(self) -> None:
        """The frame after a batch of arrivals: one layout when a row changed height,
        else a repaint."""
        moved, self._arrivals_moved_rows = self._arrivals_moved_rows, False
        if moved:
            self.view.rows_changed()
        else:
            self.view.rows_repainted()

    def _application_state_changed(self, state: Qt.ApplicationState) -> None:
        if state is Qt.ApplicationState.ApplicationSuspended:
            self.release_documents()

    def release_documents(self) -> None:
        """The laid-out documents go: the rows on screen lay theirs out again from the
        prepared formatting when they next paint. Heights stay, so no row moves."""
        self._documents.clear()

    def width_changed(self) -> None:
        """Documents and heights hold one width; prepared formatting may hold any."""
        self.release_documents()
        self._size_hints.clear()
        self._extents.clear()
        self._cached_widths.clear()
        self.forget_row_sizes()

    # Row sizes kept aligned with the model's rows

    def forget_row_sizes(self) -> None:
        """Every row is measured again, from the key-and-width cache, at the next layout: what a
        member calls when every row's preparation key changes at once (a new style or links)."""
        self._row_sizes = []
        self._row_size_keys.clear()
        self._row_sizes_for = None

    def begin_layout(self, font: QFont, width: int, rows: int) -> None:
        """A layout of `rows` rows at this font and width starts: rows answer their kept size."""
        layout = (font.key(), width)
        if layout != self._row_sizes_for or len(self._row_sizes) != rows:
            self._row_sizes = [None] * rows
            self._row_size_keys.clear()
            self._row_sizes_for = layout
        self._layout_for = layout

    def end_layout(self) -> None:
        self._layout_for = None

    def rows_inserted(self, first: int, last: int) -> None:
        """Rows arrived: each starts unmeasured; every other row keeps its size."""
        if self._row_sizes_for is not None and first <= len(self._row_sizes):
            self._row_sizes[first:first] = [None] * (last - first + 1)
        else:
            self.forget_row_sizes()

    def rows_removed(self, first: int, last: int) -> None:
        if self._row_sizes_for is not None and last < len(self._row_sizes):
            del self._row_sizes[first:last + 1]
        else:
            self.forget_row_sizes()

    def rows_data_changed(self, first: int, last: int) -> None:
        """A row's content changed: it is measured again; the others keep their sizes."""
        sizes = self._row_sizes
        for row in range(first, min(last + 1, len(sizes))):
            sizes[row] = None

    def kept_row(self, row: int, *, measured: bool = False) -> RowSize | None:
        """The row's kept size and the key it was measured under, while a layout runs (only a
        measured one when `measured`)."""
        if self._layout_for is None or row >= len(self._row_sizes):
            return None
        kept = self._row_sizes[row]
        if kept is None or kept.size is None or (measured and kept.estimated):
            return None
        return kept

    def kept_size(self, row: int, *, measured: bool = False) -> QSize | None:
        kept = self.kept_row(row, measured=measured)
        return None if kept is None else kept.size

    def hinted(self, key: Hashable, size: QSize) -> QSize:
        """What the view is told a row takes, from its size at the layout width: that size.
        A view that scrolls sideways answers the row's extent as the width (`row_extent`).
        A layout asks this of every row, so it is answered from the kept key and size with
        nothing built: a subclass that overrode `sizeHint` to widen its rows built each
        row's key again on every layout, kept size or not."""
        return size

    def keep_row_size(
        self, row: int, key: Hashable, size: QSize, font: QFont, *, estimated: bool = False
    ) -> None:
        """A row's size at the width the kept sizes are for keeps until the row changes: its
        measured size, or (away from the reader) its estimate until a slice measures it."""
        sizes, layout = self._row_sizes, self._row_sizes_for
        if layout is None or row >= len(sizes) or size.width() != layout[1]:
            return
        kept = RowSize(key, size, font, estimated)
        sizes[row] = kept
        self._row_size_keys.setdefault(key, []).append(kept)

    def forget_rows(self) -> None:
        """Every cached formatting, document and height goes, as when the rows are replaced."""
        self._prepared.clear()
        self._pending.clear()
        self.width_changed()

    def cleanup(self) -> None:
        """Stop and join every preparation this delegate started."""
        if self._stopped:
            return
        self._stopped = True
        self.preparing = False
        self._viewport_update_timer.stop()
        self.preparer.clear()
        self.stop_preparation()
        self.preparer.stop()
        self._pending.clear()

    # Qt's delegate calls

    def available_width(self, option: QStyleOptionViewItem) -> int:
        """The row's own width, or the view's viewport before the row has one."""
        width = option.rect.width() if option.rect.width() > 0 else self.view.viewport_width()
        return width if width > 0 else 800

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        painter.save()
        self.paint_background(painter, opt, index.row())
        painter.restore()
        document = self.painted_document(index, opt)
        painter.save()
        painter.translate(opt.rect.topLeft())
        painter.setClipRect(0, 0, opt.rect.width(), opt.rect.height())
        if document is None:
            # Pending: its plain text, drawn without a document laid out for it.
            painter.setFont(opt.font)
            painter.setPen(opt.palette.text().color())
            painter.drawText(0, 0, int(self.text_width(opt.rect.width())), opt.rect.height(),
                             int(Qt.TextFlag.TextWordWrap), self.row_text(index))
        else:
            context = QAbstractTextDocumentLayout.PaintContext()
            context.palette = opt.palette
            document.documentLayout().draw(painter, context)
        painter.restore()

    def painted_document(self, index: QModelIndex, option: QStyleOptionViewItem) -> QTextDocument | None:
        """The document a row paints, or None for a pending row, which paints its text plain."""
        return self.final_document(index, option.font, option.rect.width())

    def sizeHint(self, option, index) -> QSize:  # type: ignore[override]
        if (kept := self.kept_row(index.row())) is not None:
            return self.hinted(kept.key, kept.size)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        width = self.available_width(opt)
        key = self.preparation_key(index, opt.font, width)
        size = self._size_hints.get((key, width))
        if size is not None:
            self.keep_row_size(index.row(), key, size, opt.font)
            return self.hinted(key, size)
        if self.view.estimating():
            # Away from the reader: an estimate now, measured between frames.
            self._unmeasured[QPersistentModelIndex(index)] = None
            if not self._measure_timer.isActive():
                self._measure_timer.start()
            size = self.estimated_size(index, opt.font, width)
            self.keep_row_size(index.row(), key, size, opt.font, estimated=True)
            return self.hinted(key, size)
        return self.hinted(key, self.measured_size(index, opt.font, width))

    def measured_size(self, index: QModelIndex, font: QFont, width: int) -> QSize:
        """The row's height laid out at `width`, kept; a pending row's estimate, not kept, so
        its arrival lays it out once."""
        if (kept := self.kept_size(index.row(), measured=True)) is not None:
            return kept
        key = (self.preparation_key(index, font, width), width)
        size = self._size_hints.get(key)
        if size is None:
            document = self.final_document(index, font, width)
            if document is None:
                return self.estimated_size(index, font, width)
            height = int(document.size().height()) + self.ROW_PADDING
            size = self._size_hints[key] = QSize(width, height)
            self._cached_widths.setdefault(key[0], set()).add(width)
        self.keep_row_size(index.row(), key[0], size, font)
        return size

    def estimated_size(self, index: QModelIndex, font: QFont, width: int) -> QSize:
        estimate = PendingRow(self.row_text(index)).estimated_height(font, self.text_width(width))
        return QSize(width, estimate + self.ROW_PADDING)

    def is_measured(self, index: QModelIndex, font: QFont, width: int) -> bool:
        return (self.preparation_key(index, font, width), width) in self._size_hints

    def _measure_slice(self) -> None:
        """Lay out the estimated rows nearest the reader, for one slice, then the view once
        with the reader held where they are; the rest wait for the next slice."""
        view = self.view
        if self._stopped or not isinstance(view, VirtualRowView) or view.model() is None:
            self._unmeasured.clear()
            return
        reader = view.reader_row()
        waiting = sorted((index for index in self._unmeasured if index.isValid()),
                         key=lambda index: abs(index.row() - reader))
        self._unmeasured.clear()
        font, width = view.font(), view.viewport_width() or 800
        started, measured = time.monotonic(), False
        while waiting and time.monotonic() - started < self.MEASURE_SLICE_SECONDS:
            persistent = waiting.pop(0)
            index = view.model().index(persistent.row(), 0)
            if not self.is_measured(index, font, width):
                self.measured_size(index, font, width)
                measured = True
        for persistent in waiting:
            self._unmeasured[persistent] = None
        if measured:
            view.rows_changed()
        elif self._unmeasured:
            self._measure_timer.start()


class VirtualRowView(QListView):
    """A list of variable-height rows scrolled by pixel, laid out only where drawn.

    It knows whether the reader is at the newest row, keeps them there as rows arrive,
    and keeps the row under the reader in place while rows are added or removed above it.
    """

    END_SLACK = 10
    _row_connections: tuple = ()
    _layouts = 0
    """Layouts run, so a layout that found its reader by running a pending one stops there."""
    """The model signals this view's kept row sizes follow, to disconnect on the next model."""
    MEASURED_VIEWPORTS = 2
    """A layout lays out the rows within this many viewports above and below the reader's
    row; the delegate measures the rest between frames."""

    def __init__(self, delegate: RowDocumentDelegate, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows = delegate
        delegate.setParent(self)
        delegate.view = self
        self.setItemDelegate(delegate)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # noqa: N802 - Qt virtual method name
        """Move the drawn rows' pixels and repaint only what floats over them.

        Qt scrolls a viewport by moving its pixels and painting the strip that came into view,
        unless a sibling widget overlaps what it scrolls: then it repaints the whole viewport,
        every row's text again. A view with something floating over its rows (a pinned header,
        an overlay scrollbar, a jump button) repainted all of it on every frame of a glide,
        which a phone cannot do at 120 Hz (Tristan, Pixel 8a, 2026-11-18). This scrolls the
        largest part of the viewport nothing floats over, by moving its pixels, and repaints
        the parts under the floating widgets."""
        viewport = self.viewport()
        covers = self.floating_over()
        clear = self.uncovered(viewport.rect(), covers) if covers and not dx else QRect()
        if clear.isEmpty():
            super().scrollContentsBy(dx, dy)
            return
        viewport.scroll(dx, dy, clear)
        viewport.update(QRegion(viewport.rect()).subtracted(QRegion(clear)))

    def floating_over(self) -> list[QRect]:
        """Where the visible widgets floating over the viewport cover it, in its coordinates:
        this view's other children that overlap it (its scroll bars sit beside it)."""
        viewport = self.viewport()
        area = viewport.geometry()
        return [child.geometry().intersected(area).translated(-area.topLeft())
                for child in self.children()
                if isinstance(child, QWidget) and child is not viewport and child.isVisible()
                and child.geometry().intersects(area)]

    @staticmethod
    def uncovered(rect: QRect, covers: list[QRect]) -> QRect:
        """The largest rectangle of `rect` that no cover overlaps, found one cover at a time:
        each leaves the biggest of the bands above, below, left and right of it."""
        for cover in sorted(covers, key=lambda cover: cover.width() * cover.height(), reverse=True):
            if not rect.intersects(cover):
                continue
            left, top, width, height = rect.left(), rect.top(), rect.width(), rect.height()
            bands = (QRect(left, top, width, cover.top() - top),
                     QRect(left, cover.bottom() + 1, width, rect.bottom() - cover.bottom()),
                     QRect(left, top, cover.left() - left, height),
                     QRect(cover.right() + 1, top, rect.right() - cover.right(), height))
            rect = max(bands, key=lambda band: max(0, band.width()) * max(0, band.height()))
            if rect.width() <= 0 or rect.height() <= 0:
                return QRect()
        return rect

    @property
    def at_end(self) -> bool:
        scroll = self.verticalScrollBar()
        return scroll.value() >= scroll.maximum() - self.END_SLACK

    @property
    def at_start(self) -> bool:
        scroll = self.verticalScrollBar()
        return scroll.value() <= scroll.minimum()

    def follow_end(self) -> None:
        self.scrollToBottom()

    @contextmanager
    def keeping_end(self) -> Iterator[None]:
        """Rows that arrive while the reader is at the end keep the reader there."""
        was_at_end = self.at_end
        yield
        if was_at_end:
            self.executeDelayedItemsLayout()
            self.follow_end()

    @contextmanager
    def holding_position(self) -> Iterator[None]:
        """The row under the top of the viewport stays where the reader sees it."""
        index = self.indexAt(self.viewport().rect().topLeft())
        anchor = QPersistentModelIndex(index)
        offset = self.visualRect(index).top() if index.isValid() else 0
        yield
        if not anchor.isValid():
            return
        self.executeDelayedItemsLayout()
        moved = self.visualRect(self.model().index(anchor.row(), 0)).top() - offset
        scroll = self.verticalScrollBar()
        scroll.setValue(scroll.value() + moved)

    _estimating = False

    def rows_changed(self) -> None:
        """Rows may change height: lay them out again, the reader where they were (at the
        end, or on the row they read), and repaint."""
        with self.keeping_end() if self.at_end else self.holding_position():
            self.scheduleDelayedItemsLayout()
        self.viewport().update()

    def rows_repainted(self) -> None:
        """Rows changed how they are drawn at the height they had: repaint, and move none."""
        self.viewport().update()

    def estimating(self) -> bool:
        """Whether a layout of the view is running, past its measured rows."""
        return self._estimating

    def reader_row(self) -> int:
        """The row the reader reads: the newest at the end, else the one at the viewport's
        top; the newest while nothing is laid out yet."""
        model = self.model()
        count = model.rowCount() if model is not None else 0
        if self.at_end:
            # Asked before `indexAt`, which runs a pending layout first: rows that just arrived
            # under a reader at the end would otherwise lay the view out inside this layout.
            return count - 1
        top = self.indexAt(self.viewport().rect().topLeft())
        return top.row() if top.isValid() else count - 1

    def doItemsLayout(self) -> None:  # type: ignore[override]
        """Measure the rows within `MEASURED_VIEWPORTS` viewports of the reader, then lay the
        view out with every other unmeasured row at its estimate."""
        model = self.model()
        if model is None or model.rowCount() == 0:
            super().doItemsLayout()
            return
        laid_out = self._layouts
        reader, reach = self.reader_row(), self.MEASURED_VIEWPORTS * max(1, self.viewport().height())
        if self._layouts != laid_out:
            return  # finding the reader ran the pending layout, which did all of this
        font, width = self.font(), self.viewport_width() or 800
        self.rows.begin_layout(font, width, model.rowCount())
        try:
            for rows in (range(reader, model.rowCount()), range(reader - 1, -1, -1)):
                covered = 0
                for row in rows:
                    if covered >= reach:
                        break
                    covered += self.rows.measured_size(model.index(row, 0), font, width).height()
            self._estimating = True
            try:
                super().doItemsLayout()
            finally:
                self._estimating = False
        finally:
            self.rows.end_layout()
            self._layouts += 1

    def setModel(self, model) -> None:  # type: ignore[override]  # noqa: N802
        """The rows' kept sizes follow this model's inserts, removals and changes, so a layout
        after rows arrive measures only them; a reset or reordering measures every row again."""
        for signal, slot in self._row_connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass  # the previous model is already gone
        self._row_connections = ()
        self.rows.forget_row_sizes()
        super().setModel(model)
        if model is not None:
            self._row_connections = self._row_signals(model)
            for signal, slot in self._row_connections:
                signal.connect(slot)

    def _row_signals(self, model):
        rows = self.rows
        return (
            (model.rowsInserted, lambda parent, first, last: rows.rows_inserted(first, last)),
            (model.rowsRemoved, lambda parent, first, last: rows.rows_removed(first, last)),
            (model.dataChanged,
             lambda top, bottom, roles=(): rows.rows_data_changed(top.row(), bottom.row())),
            (model.modelReset, rows.forget_row_sizes),
            (model.layoutChanged, lambda *args: rows.forget_row_sizes()),
            (model.rowsMoved, lambda *args: rows.forget_row_sizes()),
        )

    def viewport_width(self) -> int:
        return self.viewport().width()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        if event.size().width() != event.oldSize().width():
            self.rows.width_changed()
        super().resizeEvent(event)
