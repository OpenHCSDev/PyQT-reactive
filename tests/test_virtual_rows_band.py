"""A layout lays out only the rows near the reader; the rest are measured between frames."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import QStringListModel

from pyqt_reactive.widgets.virtual_rows import RowDocumentDelegate, VirtualRowView
from tests.test_virtual_rows import BoldRow


class FinalRows(RowDocumentDelegate):
    """Rows whose formatting is final at once, so a layout measures what it lays out."""

    def preparation(self, index, font, width):
        return partial(BoldRow, self.row_text(index))

    def formatting(self, index, font, width):
        return BoldRow(self.row_text(index))


def all_measured(view: VirtualRowView) -> bool:
    """Nothing waits to be measured, and every row is measured at the view's width."""
    rows, model = view.rows, view.model()
    return (not rows._unmeasured and not rows._measure_timer.isActive()
            and all(rows.is_measured(model.index(row, 0), view.font(), view.viewport_width())
                    for row in range(model.rowCount())))


def shown_rows(qtbot, count: int = 400) -> tuple[VirtualRowView, QStringListModel]:
    model = QStringListModel([f"row {number}" for number in range(count)])
    view = VirtualRowView(FinalRows())
    qtbot.addWidget(view)
    view.resize(300, 200)
    view.setModel(model)
    view.show()
    return view, model


def test_a_layout_lays_out_only_the_rows_near_the_reader(qtbot) -> None:
    """Rows away from the reader stand at an estimate and are measured between frames,
    with the reader held at the end throughout."""
    view, _ = shown_rows(qtbot)
    try:
        view.follow_end()
        view.executeDelayedItemsLayout()
        measured = len(view.rows._size_hints)
        assert 0 < measured < 100
        qtbot.waitUntil(lambda: all_measured(view), timeout=10_000)
        assert view.at_end
        assert view.indexAt(view.viewport().rect().bottomLeft()).row() == 399
    finally:
        view.rows.cleanup()


def test_measuring_rows_above_keeps_the_reader_on_the_same_row(qtbot) -> None:
    view, model = shown_rows(qtbot)
    try:
        view.executeDelayedItemsLayout()
        view.scrollTo(model.index(300, 0), VirtualRowView.ScrollHint.PositionAtTop)
        top = view.indexAt(view.viewport().rect().topLeft()).row()
        qtbot.waitUntil(lambda: all_measured(view), timeout=10_000)
        assert view.indexAt(view.viewport().rect().topLeft()).row() == top
    finally:
        view.rows.cleanup()
