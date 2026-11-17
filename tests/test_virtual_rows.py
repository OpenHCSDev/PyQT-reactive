"""The virtual row family: rows paint plain until prepared, and the reader stays put."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtGui import QFont, QGuiApplication, QTextDocument

from pyqt_reactive.widgets.virtual_rows import PlainRow, RowDocumentDelegate, RowFormatting, VirtualRowView


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
        assert view.rows.formatting(index, font, 300) == PlainRow("row 3")
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


def test_measured_height_is_cached_by_key_and_dropped_when_formatting_arrives(qtbot) -> None:
    """A row is laid out into a document once per width, and re-measures only when its
    prepared formatting replaces the plain one it was measured under."""
    delegate = BoldRows()
    qtbot.addWidget(VirtualRowView(delegate))
    font = QFont()
    key = ("row 3", font.family(), font.pointSize())
    try:
        plain = delegate.measured_height(key, font, 300, PlainRow("row 3"))
        # A second call under the same key returns the cached height: the different
        # formatting it is handed is never laid out, because the key is already measured.
        assert delegate.measured_height(key, font, 300, BoldRow("row 3")) == plain
        assert (key, 300) in delegate._size_hints
        # A different width is a different measurement.
        assert (key, 150) not in delegate._size_hints
        # When the row's prepared formatting arrives, its cached height is dropped, so the
        # next measurement lays out the taller prepared row.
        delegate._row_prepared(key, BoldRow("row 3"))
        assert (key, 300) not in delegate._size_hints
        assert delegate.measured_height(key, font, 300, BoldRow("row 3")) > plain
    finally:
        delegate.cleanup()
