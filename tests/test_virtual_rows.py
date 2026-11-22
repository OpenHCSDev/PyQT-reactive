"""The virtual row family: rows stand in plain until prepared and are laid out once, in
their final form; prepared rows arrive in batches; and the reader stays put."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

from PySide6.QtCore import QSize, QStringListModel, Qt
from PySide6.QtGui import QFont, QGuiApplication, QTextDocument

from pyqt_reactive.widgets.virtual_rows import (
    PendingRow, RowDocumentDelegate, RowFormatting, RowPreparer, VirtualRowView,
)


@dataclass(frozen=True)
class BoldRow(RowFormatting):
    text: str

    def fill(self, document: QTextDocument) -> None:
        document.setHtml(f"<b>{self.text}</b><br>{self.text}")


class BoldRows(RowDocumentDelegate):
    def preparation(self, index, font, width):
        return partial(BoldRow, self.row_text(index))


def test_rows_paint_plain_until_their_formatting_is_prepared(qtbot) -> None:
    model = QStringListModel([f"row {number}" for number in range(200)])
    view = VirtualRowView(BoldRows())
    qtbot.addWidget(view)
    view.setModel(model)
    view.resize(300, 200)
    index = model.index(3, 0)
    font = QFont()
    try:
        assert view.rows.formatting(index, font, 300) == PendingRow("row 3")
        # A pending row is not laid out: no document is kept for it, and its height is an
        # estimate from its text's lines.
        assert view.rows.final_document(index, font, 300) is None
        assert not view.rows._documents and not view.rows._size_hints
        qtbot.waitUntil(lambda: view.rows.formatting(index, font, 300) == BoldRow("row 3"))
        # The prepared row lays out taller than its plain line.
        assert view.rows.row_document(index, font, 300).size().height() > plain_line_height(font)
    finally:
        view.rows.cleanup()


def plain_line_height(font: QFont) -> float:
    document = QTextDocument()
    document.setDocumentMargin(0)
    document.setDefaultFont(font)
    document.setPlainText("row 3")
    return document.size().height()


def test_rows_added_above_keep_the_reader_on_the_same_row(qtbot) -> None:
    model = QStringListModel([f"row {number}" for number in range(200)])
    view = VirtualRowView(BoldRows())
    qtbot.addWidget(view)
    view.setModel(model)
    view.resize(300, 200)
    view.show()
    try:
        view.scrollTo(model.index(100, 0), VirtualRowView.ScrollHint.PositionAtTop)
        top = view.indexAt(view.viewport().rect().topLeft()).data()
        with view.holding_position():
            model.insertRows(0, 50)
        assert view.indexAt(view.viewport().rect().topLeft()).data() == top
        view.follow_end()
        assert view.at_end
        with view.keeping_end():
            model.insertRows(model.rowCount(), 20)
        assert view.at_end
    finally:
        view.rows.cleanup()


def test_a_suspended_application_lets_row_documents_go_and_keeps_rows_in_place(qtbot) -> None:
    model = QStringListModel([f"row {number}" for number in range(50)])
    view = VirtualRowView(BoldRows())
    qtbot.addWidget(view)
    view.setModel(model)
    view.resize(300, 200)
    view.show()
    index, font = model.index(3, 0), QFont()
    try:
        qtbot.waitUntil(lambda: view.rows.formatting(index, font, 300) == BoldRow("row 3"))
        laid_out = view.rows.row_document(index, font, 300)
        place = view.visualRect(index)
        QGuiApplication.instance().applicationStateChanged.emit(Qt.ApplicationState.ApplicationSuspended)
        assert view.rows.row_document(index, font, 300) is not laid_out
        view.executeDelayedItemsLayout()
        assert view.visualRect(index) == place
    finally:
        view.rows.cleanup()


def test_measured_height_is_kept_only_for_final_formatting(qtbot) -> None:
    """A pending row's height is an estimate that is never kept, so its prepared formatting
    is laid out once when it arrives; a final row is laid out into a document once per width."""
    delegate = BoldRows()
    qtbot.addWidget(VirtualRowView(delegate))
    font = QFont()
    key = ("row 3", font.family(), font.pointSize())
    try:
        estimate = delegate.measured_height(key, font, 300, PendingRow("row 3"))
        assert estimate > 0
        assert (key, 300) not in delegate._size_hints
        laid_out = delegate.measured_height(key, font, 300, BoldRow("row 3"))
        assert (key, 300) in delegate._size_hints
        # Kept: the formatting handed on a later call is not laid out again.
        assert delegate.measured_height(key, font, 300, PendingRow("row 3")) == laid_out
        # A different width is a different measurement.
        assert (key, 150) not in delegate._size_hints
        # A member can draw a row under its key with another final look while the new one is
        # prepared (the look it last showed): the arrival drops what was laid out from it, so
        # the row lays out from what arrived.
        delegate._row_prepared(key, BoldRow("row 3"))
        assert (key, 300) not in delegate._size_hints
    finally:
        delegate.cleanup()


@dataclass(frozen=True)
class UnwrappedRow(RowFormatting):
    text: str

    def fill(self, document: QTextDocument) -> None:
        document.setHtml(f"<pre>{self.text}</pre>")


def test_a_row_measured_before_it_is_drawn_is_laid_out_once(qtbot) -> None:
    """A member that sizes a row before drawing it (a pager measuring the page it is about to
    publish) and the paint that follows read one document: the measurement keeps what it
    laid out."""
    model = QStringListModel(["row 0"])
    view = VirtualRowView(BoldRows())
    qtbot.addWidget(view)
    view.setModel(model)
    delegate, font, index = view.rows, QFont(), model.index(0, 0)
    key = delegate.preparation_key(index, font, 300)
    laid_out = []
    new_document = delegate.new_document
    def counted(*arguments):
        laid_out.append(arguments)
        return new_document(*arguments)
    delegate.new_document = counted
    try:
        delegate._row_prepared(key, BoldRow("row 0"))
        height = delegate.measured_height(key, font, 300, BoldRow("row 0"))
        document = delegate.final_document(index, font, 300)
        assert len(laid_out) == 1
        assert int(document.size().height()) + delegate.ROW_PADDING == height
    finally:
        delegate.cleanup()


def test_a_rows_extent_is_recorded_when_it_is_laid_out(qtbot) -> None:
    """Content that does not wrap is wider than the width it was laid out at; the delegate
    keeps that with the height, so asking it lays nothing out, and it outlives the documents."""
    delegate = BoldRows()
    qtbot.addWidget(VirtualRowView(delegate))
    font = QFont()
    wrapped, unwrapped = ("wrapped", font.family()), ("unwrapped", font.family())
    try:
        # Not laid out yet: the layout width.
        assert delegate.row_extent(unwrapped, 200) == 200
        delegate.measured_height(wrapped, font, 200, BoldRow("a short row"))
        delegate.measured_height(unwrapped, font, 200, UnwrappedRow("x" * 200))
        assert delegate.row_extent(wrapped, 200) == 200
        extent = delegate.row_extent(unwrapped, 200)
        assert extent > 200
        delegate.release_documents()
        assert delegate.row_extent(unwrapped, 200) == extent
        # New formatting under the key drops what was laid out from the old.
        delegate._row_prepared(unwrapped, BoldRow("now it wraps"))
        assert delegate.row_extent(unwrapped, 200) == 200
    finally:
        delegate.cleanup()


class WideRows(BoldRows):
    """Rows of a view that scrolls sideways: a row's hint is as wide as its content."""

    def preparation(self, index, font, width):
        return partial(UnwrappedRow, self.row_text(index))

    def hinted(self, key, size):
        return QSize(self.row_extent(key, size.width()), size.height())


def test_a_layout_answers_each_rows_hint_from_its_kept_key(qtbot) -> None:
    """A layout asks every row's size. A row whose size is kept answers from the kept key and
    size, widened by the subclass's own `hinted`, without building the row's key again."""
    model = QStringListModel(["x" * 200, "short"])
    view = VirtualRowView(WideRows())
    qtbot.addWidget(view)
    view.setModel(model)
    view.resize(300, 400)
    delegate = view.rows
    try:
        view.show()
        qtbot.waitUntil(lambda: all(
            delegate.is_measured(model.index(row, 0), view.font(), view.viewport_width())
            for row in range(2)), timeout=3000)
        view.doItemsLayout()
        width = view.viewport_width()
        assert view.sizeHintForIndex(model.index(0, 0)).width() > width
        assert view.sizeHintForIndex(model.index(1, 0)).width() == width
        built = []
        preparation_key = delegate.preparation_key
        def counted(*arguments):
            built.append(arguments)
            return preparation_key(*arguments)
        delegate.preparation_key = counted
        view.doItemsLayout()
        assert built == []
    finally:
        delegate.cleanup()


def test_a_page_of_rows_arrives_as_one_batch(qtbot) -> None:
    """Rows queued together are worked out by one drain of the pool's queue and reach the
    GUI thread together, so the view lays them out once rather than once per row."""
    model = QStringListModel([f"row {number}" for number in range(40)])
    view = VirtualRowView(BoldRows())
    qtbot.addWidget(view)
    view.setModel(model)
    view.resize(300, 2000)
    batches: list[int] = []
    view.rows.preparer.signals.finished.connect(lambda batch: batches.append(len(batch)))
    font = QFont()
    try:
        for row in range(40):
            view.rows.formatting(model.index(row, 0), font, 300)
        qtbot.waitUntil(lambda: sum(batches) == 40)
        assert len(batches) < 40
        assert all(view.rows.formatting(model.index(row, 0), font, 300) == BoldRow(f"row {row}")
                   for row in range(40))
    finally:
        view.rows.cleanup()


def test_a_scroll_moves_only_the_part_nothing_floats_over():
    """A pinned header across the top and an overlay bar down the right edge: the rows below the
    header and left of the bar are moved by their pixels; only the covered bands repaint."""
    from PySide6.QtCore import QRect

    from pyqt_reactive.widgets.virtual_rows import VirtualRowView

    viewport = QRect(0, 0, 400, 800)
    header, bar = QRect(0, 0, 400, 60), QRect(392, 0, 8, 800)
    assert VirtualRowView.uncovered(viewport, [header, bar]) == QRect(0, 60, 392, 740)
    assert VirtualRowView.uncovered(viewport, []) == viewport
    assert VirtualRowView.uncovered(viewport, [viewport]).isEmpty()


@dataclass(frozen=True)
class TallRow(RowFormatting):
    text: str

    def fill(self, document: QTextDocument) -> None:
        document.setHtml("<br>".join([self.text] * 6))


class CountedRows(VirtualRowView):
    laid_out = repainted = 0

    def rows_changed(self) -> None:
        self.laid_out += 1
        super().rows_changed()

    def rows_repainted(self) -> None:
        self.repainted += 1
        super().rows_repainted()


def test_a_look_that_arrives_at_the_rows_height_is_repainted_and_moves_no_row(qtbot) -> None:
    model = QStringListModel([f"row {number}" for number in range(6)])
    view = CountedRows(BoldRows())
    qtbot.addWidget(view)
    view.setModel(model)
    view.resize(300, 400)
    view.show()
    rows = view.rows
    try:
        qtbot.waitUntil(lambda: any(
            kept.size is not None and not kept.estimated
            for sizes in rows._row_size_keys.values() for kept in sizes
        ) and not rows._pending)
        qtbot.wait(50)
        key = next(key for key, sizes in rows._row_size_keys.items()
                   if any(kept.size is not None and not kept.estimated for kept in sizes))
        height = rows._row_size_keys[key][0].size.height()
        view.laid_out = view.repainted = 0

        # The same look again, as a row's new look of the same height arrives.
        rows._row_prepared(key, rows._prepared[key])
        rows._update_viewport()
        assert (view.laid_out, view.repainted) == (0, 1)
        assert rows._row_size_keys[key][0].size.height() == height

        rows._row_prepared(key, TallRow("row"))
        rows._update_viewport()
        assert (view.laid_out, view.repainted) == (1, 1)

        # Formatting prepared before any row is drawn with it changes no drawn row.
        rows._row_prepared(("not drawn yet",), BoldRow("later"))
        rows._update_viewport()
        assert (view.laid_out, view.repainted) == (1, 2)

        # A row that drew its plain text while waiting is laid out when its formatting arrives.
        rows._pending.add(("waited for",))
        rows._row_prepared(("waited for",), BoldRow("waited"))
        rows._update_viewport()
        assert (view.laid_out, view.repainted) == (2, 2)
    finally:
        rows.cleanup()


class HeldPreparer(RowPreparer):
    """Rows' work kept until the test hands a batch back: a preparer that is not a thread."""

    def __init__(self, arrived) -> None:
        super().__init__(arrived)
        self.held: dict = {}
        self.stopped = False

    def prepare(self, key, work) -> None:
        self.held[key] = work

    def land(self) -> None:
        held, self.held = self.held, {}
        self.arrived([(key, work()) for key, work in held.items()])

    def clear(self) -> None:
        self.held.clear()

    def stop(self) -> None:
        self.stopped = True


class HeldRows(BoldRows):
    def row_preparer(self) -> HeldPreparer:
        return HeldPreparer(self._rows_prepared)


def test_a_member_prepares_its_rows_where_it_says(qtbot) -> None:
    """A delegate's rows are prepared by its own preparer and nowhere else: the row's work
    goes to it once, the row stands in plain until the preparer hands it back, and closing
    the delegate drops what it had not started and joins it."""
    model = QStringListModel([f"row {number}" for number in range(5)])
    view = VirtualRowView(HeldRows())
    qtbot.addWidget(view)
    view.setModel(model)
    view.resize(300, 200)
    rows, font = view.rows, QFont()
    for _ in range(2):
        assert rows.formatting(model.index(3, 0), font, 300) == PendingRow("row 3")
    assert len(rows.preparer.held) == 1
    rows.preparer.land()
    assert rows.formatting(model.index(3, 0), font, 300) == BoldRow("row 3")
    rows.formatting(model.index(4, 0), font, 300)
    rows.cleanup()
    assert rows.preparer.stopped and not rows.preparer.held
