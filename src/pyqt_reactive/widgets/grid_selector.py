"""Select cells of a row-and-column grid by click, drag, rectangle or header.

The application supplies how its cell ids sit on the grid (``GridAddressing``)
and, optionally, the positions directly when ids do not spell them.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import ClassVar

from PyQt6.QtCore import QEvent, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetrics
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pyqt_reactive.theming import ColorScheme

logger = logging.getLogger(__name__)

GridPosition = tuple[int, int]
"""One-based (row, column)."""


class GridAddressing(ABC):
    """How an application's cell ids sit on the grid."""

    @property
    @abstractmethod
    def default_grid(self) -> tuple[int, int]:
        """(rows, columns) shown when no cell places the grid's extent."""

    @abstractmethod
    def grid_index(self, value: object) -> GridPosition | None:
        """One-based position a cell id spells; None when it spells none."""

    @abstractmethod
    def row_label(self, row: int) -> str:
        """Label of the one-based ``row``."""


class CellState(ABC):
    """How a cell button looks; names are ``ColorScheme`` attributes."""

    background: ClassVar[str]
    text: ClassVar[str]
    border: ClassVar[str | None] = None
    hover_background: ClassVar[str | None] = None

    @classmethod
    def style(cls, cs: ColorScheme) -> str:
        border = f"2px solid {cs.to_hex(getattr(cs, cls.border))}" if cls.border else "none"
        hover = (
            f"QPushButton:hover {{ background-color: "
            f"{cs.to_hex(getattr(cs, cls.hover_background))}; }}"
            if cls.hover_background
            else ""
        )
        return f"""
            QPushButton {{
                background-color: {cs.to_hex(getattr(cs, cls.background))};
                color: {cs.to_hex(getattr(cs, cls.text))};
                border: {border};
                border-radius: 3px;
            }}
            {hover}
            """


class EmptyCell(CellState):
    """A grid position no available cell occupies."""

    background = "button_disabled_bg"
    text = "button_disabled_text"


class AvailableCell(CellState):
    """A cell that can be selected."""

    background = "button_normal_bg"
    text = "button_text"
    hover_background = "button_hover_bg"


class SelectedCell(CellState):
    background = "selection_bg"
    text = "selection_text"
    border = "border_color"


@dataclass(frozen=True, slots=True)
class GridBounds:
    """Tight bounding rectangle of the occupied grid positions."""

    min_row: int
    max_row: int
    min_col: int
    max_col: int

    @property
    def rows(self) -> list[int]:
        return list(range(self.min_row, self.max_row + 1))

    @property
    def cols(self) -> list[int]:
        return list(range(self.min_col, self.max_col + 1))

    @property
    def dimensions(self) -> tuple[int, int]:
        return (self.max_row - self.min_row + 1, self.max_col - self.min_col + 1)


@dataclass(frozen=True, slots=True)
class GridModel:
    """Which cells are available and where each sits."""

    available: frozenset[str]
    cell_at_position: dict[GridPosition, str]
    position_of_cell: dict[str, GridPosition]
    dimensions: tuple[int, int]
    bounds: GridBounds | None

    @classmethod
    def empty(cls, addressing: GridAddressing) -> GridModel:
        return cls(
            available=frozenset(),
            cell_at_position={},
            position_of_cell={},
            dimensions=addressing.default_grid,
            bounds=None,
        )

    @classmethod
    def of(
        cls,
        addressing: GridAddressing,
        cell_ids: set[str],
        dimensions: tuple[int, int] | None = None,
        cell_at_position: Mapping[GridPosition, str] | None = None,
    ) -> GridModel:
        if not cell_ids:
            return cls.empty(addressing)
        positions = (
            dict(cell_at_position)
            if cell_at_position is not None
            else {
                position: cell_id
                for cell_id in cell_ids
                if (position := addressing.grid_index(cell_id)) is not None
            }
        )
        occupied = [position for position, cell_id in positions.items() if cell_id in cell_ids]
        bounds = (
            GridBounds(
                min_row=min(row for row, _ in occupied),
                max_row=max(row for row, _ in occupied),
                min_col=min(col for _, col in occupied),
                max_col=max(col for _, col in occupied),
            )
            if occupied
            else None
        )
        return cls(
            available=frozenset(cell_ids),
            cell_at_position=positions,
            position_of_cell={cell_id: position for position, cell_id in positions.items()},
            dimensions=(
                dimensions
                if dimensions is not None
                else bounds.dimensions
                if bounds is not None
                else addressing.default_grid
            ),
            bounds=bounds,
        )

    @property
    def is_empty(self) -> bool:
        return not self.available

    @property
    def rows(self) -> list[int]:
        return self.bounds.rows if self.bounds is not None else []

    @property
    def cols(self) -> list[int]:
        return self.bounds.cols if self.bounds is not None else []

    def cell_at(self, row: int, col: int) -> str | None:
        return self.cell_at_position.get((row, col))

    def cells_in_row(self, row: int) -> list[str]:
        return self._cells_where(lambda position: position[0] == row)

    def cells_in_column(self, col: int) -> list[str]:
        return self._cells_where(lambda position: position[1] == col)

    def _cells_where(self, keep: Callable[[GridPosition], bool]) -> list[str]:
        return sorted(
            cell_id
            for cell_id, position in self.position_of_cell.items()
            if keep(position) and cell_id in self.available
        )


class CellButton(QPushButton):
    """A cell button that fills its grid cell."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)


class AspectRatioContainer(QWidget):
    """Sizes its child to keep the grid's aspect ratio, centered in the available space."""

    MIN_CELL_SIZE = 8

    def __init__(self, child_widget: QWidget, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aspect_ratio = 1.0
        self.num_cols = 1
        self.num_rows = 1
        self.child_widget = child_widget
        self.child_widget.setParent(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_aspect_ratio(self, num_cols: int, num_rows: int) -> None:
        self.num_cols = num_cols
        self.num_rows = num_rows
        if num_rows > 0:
            self.aspect_ratio = num_cols / num_rows
        self.setMinimumSize(num_cols * self.MIN_CELL_SIZE, num_rows * self.MIN_CELL_SIZE)
        self._update_child_geometry()

    def resizeEvent(self, event):  # noqa: N802 - Qt virtual method name
        super().resizeEvent(event)
        self._update_child_geometry()

    def _update_child_geometry(self) -> None:
        if self.aspect_ratio <= 0:
            return
        available_w = self.width()
        available_h = self.height()
        if available_w <= 0 or available_h <= 0:
            return
        height_for_width = int(available_w / self.aspect_ratio)
        if height_for_width <= available_h:
            child_w, child_h = available_w, height_for_width
        else:
            child_w, child_h = int(available_h * self.aspect_ratio), available_h
        child_w = max(child_w, self.num_cols * self.MIN_CELL_SIZE)
        child_h = max(child_h, self.num_rows * self.MIN_CELL_SIZE)
        self.child_widget.setGeometry(
            (available_w - child_w) // 2,
            (available_h - child_h) // 2,
            child_w,
            child_h,
        )


@dataclass(slots=True)
class GridGesture:
    """The rectangle gesture in progress and the selection it started from."""

    start: object
    selection_before: frozenset[str]


class GridEventTarget(ABC):
    """What a mouse event landed on: a cell button or the grid background."""

    HANDLERS: ClassVar[Mapping[QEvent.Type, str]] = {
        QEvent.Type.MouseButtonPress: "press",
        QEvent.Type.MouseMove: "move",
        QEvent.Type.MouseButtonRelease: "release",
    }

    def __init__(self, view: GridSelectorWidget, obj: QWidget) -> None:
        self.view = view
        self.obj = obj

    def handle(self, event) -> bool | None:
        """Handled state, or None when Qt's default handling should apply."""

        handler = self.HANDLERS.get(event.type())
        return None if handler is None else getattr(self, handler)(event)

    @abstractmethod
    def grid_position(self, event): ...

    @abstractmethod
    def press(self, event) -> bool | None: ...

    def move(self, event) -> bool | None:
        if self.view.gesture is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return None
        self.view.update_rectangle(self.grid_position(event))
        event.accept()
        return True

    def release(self, event) -> bool | None:
        if event.button() != Qt.MouseButton.LeftButton or self.view.gesture is None:
            return None
        self.view.finish_gesture()
        event.accept()
        return True


class CellButtonTarget(GridEventTarget):
    def grid_position(self, event):
        return self.obj.mapTo(self.view.grid_widget, event.pos())

    def press(self, event) -> bool | None:
        if event.button() != Qt.MouseButton.LeftButton:
            return None
        cell_id = self.obj.property("cell_id")
        self.view.begin_gesture(
            self.grid_position(event),
            cell_id if cell_id in self.view.model.available else None,
        )
        event.accept()
        return True


class GridBackgroundTarget(GridEventTarget):
    def grid_position(self, event):
        return event.pos()

    def press(self, event) -> bool | None:
        if event.button() != Qt.MouseButton.LeftButton:
            return None
        if isinstance(self.view.grid_widget.childAt(event.pos()), QPushButton):
            return None
        self.view.begin_gesture(event.pos(), None)
        event.accept()
        return True


class GridSelectorWidget(QWidget):
    """A grid of cell buttons with click, drag, rectangle, header and invert selection.

    Signals:
        cells_selected: the selected cell ids after every user change.
        detach_requested: the header's detach button was clicked.
    """

    cells_selected = pyqtSignal(set)
    detach_requested = pyqtSignal()

    HEADER_STYLE = """
        QPushButton {{
            color: {text}; font-size: {size}px; border: none; background: transparent;
        }}
        QPushButton:hover {{ color: {hover_text}; background-color: {hover_bg}; }}
    """

    def __init__(
        self,
        *,
        addressing: GridAddressing,
        title: str,
        cell_noun: str,
        color_scheme: ColorScheme | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.addressing = addressing
        self.cell_noun = cell_noun
        self.color_scheme = color_scheme or ColorScheme()
        self.model = GridModel.empty(addressing)
        self.selected: set[str] = set()
        self.cell_buttons: dict[str, QPushButton] = {}
        self.gesture: GridGesture | None = None
        self._setup_ui(title)

    # -- layout ---------------------------------------------------------------

    def _setup_ui(self, title: str) -> None:
        cs = self.color_scheme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        header_layout = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-weight: bold; color: {cs.to_hex(cs.text_accent)};")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        detach_btn = QPushButton("↗")
        detach_btn.setToolTip("Detach to separate window")
        detach_btn.setFixedWidth(30)
        detach_btn.setStyleSheet(cs.styles.generate_button_style())
        detach_btn.clicked.connect(lambda: self.detach_requested.emit())
        header_layout.addWidget(detach_btn)
        clear_btn = QPushButton("Clear Selection")
        clear_btn.setStyleSheet(cs.styles.generate_button_style())
        clear_btn.clicked.connect(lambda: self.clear_selection())
        header_layout.addWidget(clear_btn)
        layout.addLayout(header_layout)

        grid_container = QFrame()
        grid_container.setStyleSheet(
            f"background-color: {cs.to_hex(cs.panel_bg)}; border-radius: 3px;"
        )
        grid_layout_wrapper = QVBoxLayout(grid_container)
        grid_layout_wrapper.setContentsMargins(10, 10, 10, 10)

        self.grid_widget = QWidget()
        self.grid_widget.setMouseTracking(True)
        self.cell_grid_layout = QGridLayout(self.grid_widget)
        self.cell_grid_layout.setSpacing(2)
        self.cell_grid_layout.setContentsMargins(0, 0, 0, 0)
        self.aspect_container = AspectRatioContainer(self.grid_widget)
        self.grid_widget.installEventFilter(self)

        self.selection_rect_widget = QLabel(self.grid_widget)
        self.selection_rect_widget.setStyleSheet(f"""
            background-color: {cs.to_hex(cs.selection_bg)}40;
            border: 2px solid {cs.to_hex(cs.selection_bg)};
        """)
        self.selection_rect_widget.hide()
        self.selection_rect_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        grid_layout_wrapper.addWidget(self.aspect_container, 1)
        layout.addWidget(grid_container, 1)

        self.status_label = QLabel(f"No {self.cell_noun}")
        self.status_label.setStyleSheet(f"color: {cs.to_hex(cs.text_secondary)};")
        layout.addWidget(self.status_label)

    def set_available_cells(
        self,
        cell_ids: set[str],
        dimensions: tuple[int, int] | None = None,
        cell_at_position: Mapping[GridPosition, str] | None = None,
    ) -> None:
        """Show ``cell_ids`` as selectable; positions come from the ids or are given."""

        self.model = GridModel.of(self.addressing, cell_ids, dimensions, cell_at_position)
        self.selected &= self.model.available
        if self.model.is_empty:
            self._clear_grid()
            self.status_label.setText(f"No {self.cell_noun}")
            return
        self._build_grid()
        self._update_status()

    def _clear_grid(self) -> None:
        self.cell_buttons.clear()
        while self.cell_grid_layout.count():
            item = self.cell_grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _header_button(self, text: str, size: int) -> QPushButton:
        cs = self.color_scheme
        button = QPushButton(text)
        button.setFlat(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            self.HEADER_STYLE.format(
                text=cs.to_hex(cs.text_secondary),
                size=size,
                hover_text=cs.to_hex(cs.text_primary),
                hover_bg=cs.to_hex(cs.panel_bg),
            )
        )
        return button

    def _build_grid(self) -> None:
        self._clear_grid()
        rows, cols = self.model.rows, self.model.cols
        if not rows or not cols:
            return

        font = QFont()
        font.setPointSize(10)
        metrics = QFontMetrics(font)
        min_header_width = max(metrics.horizontalAdvance(str(cols[-1])) + 8, 15)
        min_header_height = max(metrics.height() + 4, 15)

        invert_btn = self._header_button("⇄", 12)
        invert_btn.setMinimumSize(18, 18)
        invert_btn.setToolTip("Invert Selection")
        invert_btn.clicked.connect(lambda: self.invert_selection())
        self.cell_grid_layout.addWidget(invert_btn, 0, 0)

        for grid_col, col in enumerate(cols, start=1):
            header = self._header_button(str(col), 10)
            header.setMinimumSize(min_header_width, 18)
            header.setMaximumHeight(18)
            header.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            header.clicked.connect(
                lambda _checked, c=col: self._toggle(self.model.cells_in_column(c))
            )
            self.cell_grid_layout.addWidget(header, 0, grid_col)

        for grid_row, row in enumerate(rows, start=1):
            header = self._header_button(self.addressing.row_label(row), 10)
            header.setMinimumSize(18, min_header_height)
            header.setMaximumWidth(18)
            header.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Ignored)
            header.clicked.connect(lambda _checked, r=row: self._toggle(self.model.cells_in_row(r)))
            self.cell_grid_layout.addWidget(header, grid_row, 0)

            for grid_col, col in enumerate(cols, start=1):
                self.cell_grid_layout.addWidget(self._cell_button(row, col), grid_row, grid_col)

        for grid_col in range(1, len(cols) + 1):
            self.cell_grid_layout.setColumnStretch(grid_col, 1)
        for grid_row in range(1, len(rows) + 1):
            self.cell_grid_layout.setRowStretch(grid_row, 1)
        self.aspect_container.set_aspect_ratio(len(cols) + 1, len(rows) + 1)

    def _cell_button(self, row: int, col: int) -> QPushButton:
        cell_id = self.model.cell_at(row, col)
        button = CellButton()
        size = AspectRatioContainer.MIN_CELL_SIZE
        button.setMinimumSize(size, size)
        button.setCheckable(True)
        button.installEventFilter(self)
        if cell_id is not None and cell_id in self.model.available:
            selected = cell_id in self.selected
            button.setChecked(selected)
            button.setStyleSheet(
                (SelectedCell if selected else AvailableCell).style(self.color_scheme)
            )
            button.setProperty("cell_id", cell_id)
            self.cell_buttons[cell_id] = button
        else:
            button.setEnabled(False)
            button.setStyleSheet(EmptyCell.style(self.color_scheme))
            button.setProperty("cell_id", None)
        return button

    # -- selection ----------------------------------------------------------------

    def _set_selected(self, cell_id: str, selected: bool) -> None:
        button = self.cell_buttons.get(cell_id)
        if button is None or (cell_id in self.selected) == selected:
            return
        if selected:
            self.selected.add(cell_id)
        else:
            self.selected.discard(cell_id)
        button.setChecked(selected)
        button.setStyleSheet((SelectedCell if selected else AvailableCell).style(self.color_scheme))

    def _publish(self) -> None:
        self._update_status()
        self.cells_selected.emit(self.selected.copy())

    def _toggle(self, cell_ids: list[str]) -> None:
        if not cell_ids:
            return
        select = not all(cell_id in self.selected for cell_id in cell_ids)
        for cell_id in cell_ids:
            self._set_selected(cell_id, select)
        self._publish()

    def select_cells(self, cell_ids: set[str], *, emit_signal: bool = True) -> None:
        """Make ``cell_ids`` (those available) the selection."""

        for cell_id in tuple(self.selected):
            self._set_selected(cell_id, False)
        for cell_id in cell_ids:
            self._set_selected(cell_id, True)
        self._update_status()
        if emit_signal:
            self.cells_selected.emit(self.selected.copy())

    def clear_selection(self, *, emit_signal: bool = True) -> None:
        self.select_cells(set(), emit_signal=emit_signal)

    def invert_selection(self) -> None:
        inverted = set(self.model.available) - self.selected
        self.select_cells(inverted, emit_signal=False)
        self._publish()

    def _update_status(self) -> None:
        text = f"{len(self.model.available)} {self.cell_noun} available"
        if self.selected:
            text += f" | {len(self.selected)} selected"
        self.status_label.setText(text)

    # -- gestures -----------------------------------------------------------------

    def eventFilter(self, obj, event):  # noqa: N802 - Qt virtual method name
        if isinstance(obj, QPushButton):
            target = CellButtonTarget(self, obj)
        elif obj is self.grid_widget:
            target = GridBackgroundTarget(self, obj)
        else:
            return super().eventFilter(obj, event)
        handled = target.handle(event)
        return super().eventFilter(obj, event) if handled is None else handled

    def begin_gesture(self, start, cell_id: str | None) -> None:
        """Start a rectangle at ``start``; on a cell, also toggle it and paint by drag."""

        self.gesture = GridGesture(start=start, selection_before=frozenset(self.selected))
        self.grid_widget.grabMouse()
        self._show_rectangle(QRect(start, start).normalized())
        if cell_id is not None:
            self._set_selected(cell_id, cell_id not in self.selected)
            self._publish()

    def update_rectangle(self, current) -> None:
        rect = QRect(self.gesture.start, current).normalized()
        self._show_rectangle(rect)
        inside = {
            cell_id
            for cell_id, button in self.cell_buttons.items()
            if rect.intersects(QRect(button.pos(), button.size()))
        }
        for cell_id in self.model.available:
            self._set_selected(
                cell_id,
                cell_id in inside or cell_id in self.gesture.selection_before,
            )
        self._publish()

    def finish_gesture(self) -> None:
        self.grid_widget.releaseMouse()
        self.gesture = None
        self.selection_rect_widget.hide()

    def _show_rectangle(self, rect: QRect) -> None:
        self.selection_rect_widget.setGeometry(rect)
        self.selection_rect_widget.raise_()
        self.selection_rect_widget.show()
