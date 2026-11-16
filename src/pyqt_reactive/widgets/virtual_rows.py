"""Rows drawn as rich-text documents in a virtual list.

Only the rows on screen are laid out. Each row's document and height are cached by the
row, its font and the width it is laid out at. A row's expensive formatting is prepared
on the delegate's thread pool while the row paints plain, and a finished preparation
repaints the viewport once per frame however many rows finish in it.
"""

from __future__ import annotations

from abc import abstractmethod
from collections import OrderedDict
from collections.abc import Callable, Hashable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from PySide6.QtCore import (
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAbstractTextDocumentLayout, QFont, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)


class RowFormatting:
    """How one row's text is formatted in its document."""

    @abstractmethod
    def fill(self, document: QTextDocument) -> None: ...


@dataclass(frozen=True)
class PlainRow(RowFormatting):
    """A row whose formatting is not prepared yet paints its plain text."""

    text: str

    def fill(self, document: QTextDocument) -> None:
        document.setPlainText(self.text)


@dataclass(frozen=True)
class HtmlRow(RowFormatting):
    """A row drawn from rich text prepared for it."""

    html: str

    def fill(self, document: QTextDocument) -> None:
        document.setHtml(self.html)


class PreparedRowSignals(QObject):
    """A finished preparation: the key it was prepared under and its formatting."""

    finished = Signal(object, object)


class RowPreparation(QRunnable):
    """One row's formatting, worked out on the pool; the delegate applies it on the GUI thread."""

    def __init__(self, key: Hashable, prepare: Callable[[], RowFormatting], signals: PreparedRowSignals) -> None:
        super().__init__()
        self.key = key
        self.prepare = prepare
        self.signals = signals

    def run(self) -> None:
        self.signals.finished.emit(self.key, self.prepare())


class DetachedRows:
    """Rows no view draws yet: nothing to lay out again or repaint, and no viewport width."""

    def rows_changed(self) -> None:
        """No view, so nothing to lay out again."""

    def viewport_width(self) -> int:
        return 0


class RowDocumentDelegate(QStyledItemDelegate):
    """Paints each row as a QTextDocument at the view's width.

    A member says what a row is keyed by, what its plain text is, how its formatting is
    prepared off the GUI thread and how a prepared formatting fills a document. Rows
    whose formatting is still being prepared paint their plain text.
    """

    MAX_PREPARED_ROWS = 10_000
    MAX_DOCUMENTS = 500
    ROW_PADDING = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.view: DetachedRows | VirtualRowView = DetachedRows()
        # One worker thread and its signals share this delegate's lifetime.
        self._thread_pool = QThreadPool(self)
        self._thread_pool.setMaxThreadCount(1)
        self._prepared_signals = PreparedRowSignals(self._thread_pool)
        self._prepared_signals.finished.connect(self._row_prepared)
        self.preparing = True
        self._stopped = False
        self._prepared: OrderedDict[Hashable, RowFormatting] = OrderedDict()
        self._pending: set[Hashable] = set()
        self._documents: OrderedDict[tuple[Hashable, int], QTextDocument] = OrderedDict()
        self._size_hints: dict[tuple[Hashable, int], QSize] = {}
        # Finished preparations repaint once per frame, however many arrive in it.
        self._viewport_update_timer = QTimer(self)
        self._viewport_update_timer.setSingleShot(True)
        self._viewport_update_timer.setInterval(16)
        self._viewport_update_timer.timeout.connect(self._update_viewport)

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
        """The formatting prepared under `key`, starting `prepare` on the pool the first time."""
        if key in self._prepared:
            self._prepared.move_to_end(key)
            return self._prepared[key]
        if self.preparing and key not in self._pending:
            self._pending.add(key)
            self._thread_pool.start(RowPreparation(key, prepare, self._prepared_signals))
        return PlainRow(text)

    def row_document(self, index: QModelIndex, font: QFont, width: int) -> QTextDocument:
        key = (self.preparation_key(index, font, width), width)
        document = self._documents.get(key)
        if document is not None:
            self._documents.move_to_end(key)
            return document
        document = self.new_document(font, width)
        self.formatting(index, font, width).fill(document)
        self._documents[key] = document
        if len(self._documents) > self.MAX_DOCUMENTS:
            self._documents.popitem(last=False)
        return document

    def new_document(self, font: QFont, width: int) -> QTextDocument:
        document = QTextDocument()
        # No margin: a row's text starts where the row does.
        document.setDocumentMargin(0)
        document.setDefaultFont(font)
        document.setTextWidth(self.text_width(width))
        return document

    def _row_prepared(self, key: Hashable, prepared: RowFormatting) -> None:
        if self._stopped:
            return
        self._pending.discard(key)
        self._prepared[key] = prepared
        if len(self._prepared) > self.MAX_PREPARED_ROWS:
            self._prepared.popitem(last=False)
        # The row's plain documents and heights give way to the prepared ones.
        for document_key in [entry for entry in self._documents if entry[0] == key]:
            del self._documents[document_key]
        for size_key in [entry for entry in self._size_hints if entry[0] == key]:
            del self._size_hints[size_key]
        if not self._viewport_update_timer.isActive():
            self._viewport_update_timer.start()

    def _update_viewport(self) -> None:
        self.view.rows_changed()

    def width_changed(self) -> None:
        """Documents and heights hold one width; prepared formatting may hold any."""
        self._documents.clear()
        self._size_hints.clear()

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
        context = QAbstractTextDocumentLayout.PaintContext()
        context.palette = opt.palette
        painter.save()
        painter.translate(opt.rect.topLeft())
        painter.setClipRect(0, 0, opt.rect.width(), opt.rect.height())
        document.documentLayout().draw(painter, context)
        painter.restore()

    def painted_document(self, index: QModelIndex, option: QStyleOptionViewItem) -> QTextDocument:
        return self.row_document(index, option.font, option.rect.width())

    def sizeHint(self, option, index) -> QSize:  # type: ignore[override]
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        width = self.available_width(opt)
        key = (self.preparation_key(index, opt.font, width), width)
        size = self._size_hints.get(key)
        if size is None:
            height = int(self.row_document(index, opt.font, width).size().height())
            size = self._size_hints[key] = QSize(width, height + self.ROW_PADDING)
        return size


class VirtualRowView(QListView):
    """A list of variable-height rows scrolled by pixel, laid out only where drawn.

    It knows whether the reader is at the newest row, keeps them there as rows arrive,
    and keeps the row under the reader in place while rows are added or removed above it.
    """

    END_SLACK = 10

    def __init__(self, delegate: RowDocumentDelegate, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows = delegate
        delegate.setParent(self)
        delegate.view = self
        self.setItemDelegate(delegate)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

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

    def rows_changed(self) -> None:
        """Prepared rows may change height: lay them out again and repaint."""
        self.scheduleDelayedItemsLayout()
        self.viewport().update()

    def viewport_width(self) -> int:
        return self.viewport().width()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        if event.size().width() != event.oldSize().width():
            self.rows.width_changed()
        super().resizeEvent(event)
