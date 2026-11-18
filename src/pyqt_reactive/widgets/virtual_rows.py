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

from abc import abstractmethod
import math
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Hashable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

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


class DetachedRows:
    """Rows no view draws yet: nothing to lay out again or repaint, and no viewport width."""

    def rows_changed(self) -> None:
        """No view, so nothing to lay out again."""

    def viewport_width(self) -> int:
        return 0

    def estimating(self) -> bool:
        """No view lays rows out, so every row asked for is measured."""
        return False


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
        # One worker thread and its signals share this delegate's lifetime.
        self._thread_pool = QThreadPool(self)
        self._thread_pool.setMaxThreadCount(1)
        self._prepared_signals = PreparedRowSignals(self._thread_pool)
        self._prepared_signals.finished.connect(self._rows_prepared)
        self._queue = PreparationQueue()
        self.preparing = True
        self._stopped = False
        self._prepared: OrderedDict[Hashable, RowFormatting] = OrderedDict()
        self._pending: set[Hashable] = set()
        self._documents: OrderedDict[tuple[Hashable, int], QTextDocument] = OrderedDict()
        self._size_hints: dict[tuple[Hashable, int], QSize] = {}
        # The widths each key has a document or height cached at, so an arrival drops them.
        self._cached_widths: dict[Hashable, set[int]] = {}
        # A batch of finished preparations lays the view out once, in the next frame.
        self._viewport_update_timer = QTimer(self)
        self._viewport_update_timer.setSingleShot(True)
        self._viewport_update_timer.setInterval(16)
        self._viewport_update_timer.timeout.connect(self._update_viewport)
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
        """Close whatever the preparations run through; the pool itself is joined after."""

    # Caches

    def formatting(self, index: QModelIndex, font: QFont, width: int) -> RowFormatting:
        """The row's prepared formatting, or its plain text while that is being prepared."""
        return self.keyed_formatting(self.preparation_key(index, font, width), self.row_text(index),
                                     self.preparation(index, font, width))

    def keyed_formatting(self, key: Hashable, text: str, prepare: Callable[[], RowFormatting]) -> RowFormatting:
        """The formatting prepared under `key`, queueing `prepare` on the pool the first time;
        a `PendingRow` stands in until it arrives."""
        if key in self._prepared:
            self._prepared.move_to_end(key)
            return self._prepared[key]
        if self.preparing and key not in self._pending:
            self._pending.add(key)
            if self._queue.add(key, prepare):
                self._thread_pool.start(RowPreparations(self._queue, self._prepared_signals))
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
        document = self.new_document(font, width)
        formatting.fill(document)
        self._documents[key] = document
        self._cached_widths.setdefault(key[0], set()).add(width)
        if len(self._documents) > self.MAX_DOCUMENTS:
            self._documents.popitem(last=False)
        return document

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
        document = self.new_document(font, width)
        formatting.fill(document)
        size = self._size_hints[cache_key] = QSize(width, int(document.size().height()) + self.ROW_PADDING)
        self._cached_widths.setdefault(key, set()).add(width)
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
        from this. The view lays out again in the next frame, once however many arrive."""
        if self._stopped:
            return
        self._pending.discard(key)
        self._prepared[key] = prepared
        if len(self._prepared) > self.MAX_PREPARED_ROWS:
            self._prepared.popitem(last=False)
        for width in self._cached_widths.pop(key, ()):
            self._documents.pop((key, width), None)
            self._size_hints.pop((key, width), None)
        if not self._viewport_update_timer.isActive():
            self._viewport_update_timer.start()

    def _update_viewport(self) -> None:
        self.view.rows_changed()

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
        self._cached_widths.clear()

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
        self._queue.clear()
        self._thread_pool.clear()
        self.stop_preparation()
        self._thread_pool.waitForDone()
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
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        width = self.available_width(opt)
        size = self._size_hints.get((self.preparation_key(index, opt.font, width), width))
        if size is not None:
            return size
        if self.view.estimating():
            # Away from the reader: an estimate now, measured between frames.
            self._unmeasured[QPersistentModelIndex(index)] = None
            if not self._measure_timer.isActive():
                self._measure_timer.start()
            return self.estimated_size(index, opt.font, width)
        return self.measured_size(index, opt.font, width)

    def measured_size(self, index: QModelIndex, font: QFont, width: int) -> QSize:
        """The row's height laid out at `width`, kept; a pending row's estimate, not kept, so
        its arrival lays it out once."""
        key = (self.preparation_key(index, font, width), width)
        size = self._size_hints.get(key)
        if size is not None:
            return size
        document = self.final_document(index, font, width)
        if document is None:
            return self.estimated_size(index, font, width)
        size = self._size_hints[key] = QSize(width, int(document.size().height()) + self.ROW_PADDING)
        self._cached_widths.setdefault(key[0], set()).add(width)
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

    def estimating(self) -> bool:
        """Whether a layout of the view is running, past its measured rows."""
        return self._estimating

    def reader_row(self) -> int:
        """The row the reader reads: the newest at the end, else the one at the viewport's
        top; the newest while nothing is laid out yet."""
        model = self.model()
        count = model.rowCount() if model is not None else 0
        top = self.indexAt(self.viewport().rect().topLeft())
        return top.row() if top.isValid() and not self.at_end else count - 1

    def doItemsLayout(self) -> None:  # type: ignore[override]
        """Measure the rows within `MEASURED_VIEWPORTS` viewports of the reader, then lay the
        view out with every other unmeasured row at its estimate."""
        model = self.model()
        if model is None or model.rowCount() == 0:
            super().doItemsLayout()
            return
        reader, reach = self.reader_row(), self.MEASURED_VIEWPORTS * max(1, self.viewport().height())
        font, width = self.font(), self.viewport_width() or 800
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

    def viewport_width(self) -> int:
        return self.viewport().width()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        if event.size().width() != event.oldSize().width():
            self.rows.width_changed()
        super().resizeEvent(event)
