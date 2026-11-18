"""The virtual row family: rows stand in plain until prepared and are laid out once, in
their final form; prepared rows arrive in batches; and the reader stays put."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtGui import QFont, QGuiApplication, QTextDocument

from pyqt_reactive.widgets.virtual_rows import PendingRow, RowDocumentDelegate, RowFormatting, VirtualRowView


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
    view.rows._prepared_signals.finished.connect(lambda batch: batches.append(len(batch)))
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
