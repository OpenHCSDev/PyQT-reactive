"""Grid selection over an application's cell addressing."""

from __future__ import annotations

from PyQt6.QtCore import QPoint

from pyqt_reactive.widgets.grid_selector import GridAddressing, GridModel, GridSelectorWidget


class LetterRowAddressing(GridAddressing):
    """Cell ids like ``B2``: a row letter and a column number."""

    default_grid = (8, 12)

    def grid_index(self, value: object) -> tuple[int, int] | None:
        text = str(value)
        if len(text) < 2 or not text[0].isalpha() or not text[1:].isdigit():
            return None
        return (ord(text[0].upper()) - ord("A") + 1, int(text[1:]))

    def row_label(self, row: int) -> str:
        return chr(ord("A") + row - 1)


LetterRows = LetterRowAddressing()


def test_model_places_cells_by_their_ids_and_bounds_the_grid() -> None:
    model = GridModel.of(LetterRows, {"B2", "C4", "nonsense"})

    assert model.cell_at(2, 2) == "B2" and model.position_of_cell["C4"] == (3, 4)
    assert (model.rows, model.cols) == ([2, 3], [2, 3, 4])
    assert model.dimensions == (2, 3)
    assert GridModel.of(LetterRows, set()).dimensions == (8, 12)


def test_model_uses_supplied_positions_and_dimensions() -> None:
    model = GridModel.of(
        LetterRows,
        {"R02C03", "R04C05"},
        dimensions=(16, 24),
        cell_at_position={(2, 3): "R02C03", (4, 5): "R04C05"},
    )

    assert (model.rows, model.cols) == ([2, 3, 4], [3, 4, 5])
    assert model.cell_at(4, 5) == "R04C05" and model.cell_at(3, 4) is None
    assert model.dimensions == (16, 24)


def test_model_lists_available_cells_by_row_and_column() -> None:
    model = GridModel.of(LetterRows, {"A1", "A2", "B1"})

    assert model.cells_in_row(1) == ["A1", "A2"]
    assert model.cells_in_column(1) == ["A1", "B1"]


def test_widget_selects_inverts_and_clears(qapp) -> None:
    widget = GridSelectorWidget(addressing=LetterRows, title="Grid", cell_noun="cells")
    published: list[set[str]] = []
    widget.cells_selected.connect(published.append)
    widget.set_available_cells({"A1", "A2"})

    widget.select_cells({"A1", "Z9"}, emit_signal=False)
    assert widget.selected == {"A1"} and published == []

    widget.invert_selection()
    assert widget.selected == {"A2"} and published == [{"A2"}]
    assert widget.status_label.text() == "2 cells available | 1 selected"

    widget.clear_selection(emit_signal=False)
    assert widget.selected == set()


def test_rectangle_gesture_adds_to_the_selection_it_started_from(qapp) -> None:
    widget = GridSelectorWidget(addressing=LetterRows, title="Grid", cell_noun="cells")
    widget.set_available_cells({"A1", "A2", "B1", "B2"})
    widget.resize(400, 400)
    widget.show()
    qapp.processEvents()
    widget.select_cells({"B2"}, emit_signal=False)

    a1 = widget.cell_buttons["A1"]
    a2 = widget.cell_buttons["A2"]
    widget.begin_gesture(a1.pos() + QPoint(1, 1), None)
    widget.update_rectangle(a2.pos() + QPoint(1, 1))
    widget.finish_gesture()

    assert widget.selected == {"A1", "A2", "B2"}
    assert widget.gesture is None
    widget.close()
