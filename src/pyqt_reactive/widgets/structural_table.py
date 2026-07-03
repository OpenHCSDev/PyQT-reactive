"""Generic structural semantics helpers for editable Qt tables."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, fields as dataclass_fields, is_dataclass

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import QWidget, QTableWidget
from objectstate import (
    ObjectStateSubfieldSemantic,
    ObjectStateSubfieldSemanticIndex,
    StructuralFieldPath,
    StructuralValuePath,
)


def _widget_rect_in(widget: QWidget, ancestor: QWidget) -> QRect:
    top_left = ancestor.mapFromGlobal(widget.mapToGlobal(QPoint(0, 0)))
    return QRect(top_left, widget.size())


def _unique_widgets(widgets: list[QWidget]) -> tuple[QWidget, ...]:
    unique: list[QWidget] = []
    seen: set[int] = set()
    for widget in widgets:
        widget_id = id(widget)
        if widget_id in seen:
            continue
        unique.append(widget)
        seen.add(widget_id)
    return tuple(unique)


class StructuralFlashTarget(ABC):
    """Nominal visual target that can register its own flash geometry."""

    @abstractmethod
    def register_flash(self, manager, key: str) -> None:
        """Register this target with a form manager's flash system."""
        pass

    @abstractmethod
    def scroll_widget(self) -> QWidget:
        """Return a concrete widget suitable for scroll positioning."""
        pass

    @abstractmethod
    def scroll_rect_in(self, ancestor: QWidget) -> QRect | None:
        """Return this target's precise rectangle in an ancestor widget."""
        pass

    @abstractmethod
    def mask_rects_in_window(self, window: QWidget) -> tuple[tuple[QRect, bool], ...]:
        """Return precise rectangles to subtract from a containing flash."""
        pass

    def layout_watch_widgets(self) -> tuple[QWidget, ...]:
        """Return widgets whose geometry contributes to this target."""
        return (self.scroll_widget(),)


@dataclass(frozen=True, slots=True)
class StructuralTableCellTarget(StructuralFlashTarget):
    """Concrete visual target for one structural table cell."""

    table: QTableWidget
    row_index: int
    column_index: int
    cell_widget: QWidget | None

    def register_flash(self, manager, key: str) -> None:
        manager.register_flash_table_cell_rect(key, self)

    def scroll_widget(self) -> QWidget:
        return self.cell_widget if self.cell_widget is not None else self.table

    def _cell_rect(self) -> QRect | None:
        model_index = self.table.model().index(self.row_index, self.column_index)
        if not model_index.isValid():
            return None
        cell_rect = self.table.visualRect(model_index)
        if cell_rect.isNull():
            return None
        return cell_rect

    def _cell_rect_in(self, ancestor: QWidget) -> QRect | None:
        if self.cell_widget is not None:
            return _widget_rect_in(self.cell_widget, ancestor)
        cell_rect = self._cell_rect()
        if cell_rect is None:
            return None
        top_left = ancestor.mapFromGlobal(
            self.table.viewport().mapToGlobal(cell_rect.topLeft())
        )
        return QRect(top_left, cell_rect.size())

    def scroll_rect_in(self, ancestor: QWidget) -> QRect | None:
        return self._cell_rect_in(ancestor)

    def mask_rects_in_window(self, window: QWidget) -> tuple[tuple[QRect, bool], ...]:
        rect = self._cell_rect_in(window)
        return () if rect is None else ((rect, False),)

    def layout_watch_widgets(self) -> tuple[QWidget, ...]:
        widgets = [self.table, self.table.viewport()]
        if self.cell_widget is not None:
            widgets.append(self.cell_widget)
        return _unique_widgets(widgets)


@dataclass(frozen=True, slots=True)
class StructuralWidgetTarget(StructuralFlashTarget):
    """Concrete visual target for one structural child widget."""

    widget: QWidget

    def register_flash(self, manager, key: str) -> None:
        manager.register_flash_widget_rect(key, self.widget)

    def scroll_widget(self) -> QWidget:
        return self.widget

    def scroll_rect_in(self, ancestor: QWidget) -> QRect | None:
        return _widget_rect_in(self.widget, ancestor)

    def mask_rects_in_window(self, window: QWidget) -> tuple[tuple[QRect, bool], ...]:
        return ((_widget_rect_in(self.widget, window), False),)


@dataclass(frozen=True, slots=True)
class StructuralWidgetSetTarget(StructuralFlashTarget):
    """Structural target represented by a set of concrete widgets."""

    widgets: tuple[QWidget, ...]

    def register_flash(self, manager, key: str) -> None:
        if not self.widgets:
            return
        manager.register_flash_masked_container(
            key,
            self.scroll_widget(),
            self.mask_rects_in_window,
            layout_watch_widgets=self.layout_watch_widgets(),
        )

    def scroll_widget(self) -> QWidget:
        return self.widgets[0]

    def scroll_rect_in(self, ancestor: QWidget) -> QRect | None:
        rects = [
            _widget_rect_in(widget, ancestor)
            for widget in self.widgets
            if widget.isVisibleTo(ancestor)
        ]
        if not rects:
            return None
        target = QRect(rects[0])
        for rect in rects[1:]:
            target = target.united(rect)
        return target

    def mask_rects_in_window(self, window: QWidget) -> tuple[tuple[QRect, bool], ...]:
        from pyqt_reactive.animation.flash_mixin import (
            get_child_mask_rect,
            needs_square_checkbox_mask,
        )

        return tuple(
            (get_child_mask_rect(widget, window), needs_square_checkbox_mask(widget))
            for widget in self.widgets
            if widget.isVisibleTo(window)
        )

    def layout_watch_widgets(self) -> tuple[QWidget, ...]:
        return _unique_widgets(list(self.widgets))


@dataclass(frozen=True, slots=True)
class StructuralDescendantMaskTarget(StructuralFlashTarget):
    """Structural target that masks the readable descendants of a container."""

    container: QWidget

    def register_flash(self, manager, key: str) -> None:
        manager.register_flash_masked_container(
            key,
            self.container,
            self.mask_rects_in_window,
            layout_watch_widgets=self.layout_watch_widgets(),
        )

    def scroll_widget(self) -> QWidget:
        return self.container

    def scroll_rect_in(self, ancestor: QWidget) -> QRect | None:
        return _widget_rect_in(self.container, ancestor)

    def mask_rects_in_window(self, window: QWidget) -> tuple[tuple[QRect, bool], ...]:
        from pyqt_reactive.animation.flash_mixin import (
            container_descendant_mask_rects,
        )

        return tuple(container_descendant_mask_rects(self.container, window))

    def layout_watch_widgets(self) -> tuple[QWidget, ...]:
        from pyqt_reactive.animation.flash_mixin import (
            container_descendant_mask_watch_widgets,
        )

        return _unique_widgets(
            [self.container, *container_descendant_mask_watch_widgets(self.container)]
        )


@dataclass(frozen=True, slots=True)
class StructuralMaskedContainerTarget(StructuralFlashTarget):
    """Flash a structural container while masking one descendant target."""

    container: QWidget
    masked_target: StructuralFlashTarget
    label_widget: QWidget | None = None
    scroll_target: StructuralFlashTarget | None = None

    def register_flash(self, manager, key: str) -> None:
        manager.register_flash_masked_container(
            key,
            self.container,
            self.mask_rects_in_window,
            label_widget=self.label_widget,
            layout_watch_widgets=self.layout_watch_widgets(),
        )

    def scroll_widget(self) -> QWidget:
        return (self.scroll_target or self.masked_target).scroll_widget()

    def scroll_rect_in(self, ancestor: QWidget) -> QRect | None:
        return (self.scroll_target or self.masked_target).scroll_rect_in(ancestor)

    def mask_rects_in_window(self, window: QWidget) -> tuple[tuple[QRect, bool], ...]:
        masks = list(self.masked_target.mask_rects_in_window(window))
        if self.label_widget is not None:
            label_rect = _widget_rect_in(self.label_widget, window)
            if label_rect.isValid() and not label_rect.isNull():
                masks.append((label_rect, False))
        return tuple(masks)

    def layout_watch_widgets(self) -> tuple[QWidget, ...]:
        widgets = [self.container, *self.masked_target.layout_watch_widgets()]
        if self.scroll_target is not None:
            widgets.extend(self.scroll_target.layout_watch_widgets())
        if self.label_widget is not None:
            widgets.append(self.label_widget)
        return _unique_widgets(widgets)


@dataclass(frozen=True, slots=True)
class InlineDataclassStructuralTarget:
    """Resolved structural target exposed by an inline dataclass editor."""

    child_field_name: str
    target: StructuralFlashTarget


def resolve_inline_dataclass_structural_target(
    *,
    inline_widget: QWidget | None,
    inline_field_path: tuple[str, ...],
    display_path: str,
    owner_child_field_name: str | None = None,
) -> InlineDataclassStructuralTarget | None:
    """Resolve an inline dataclass structural visual target through widget contracts."""

    from pyqt_reactive.protocols import (
        ChildFieldIdentityProvider,
        ChildSubfieldNavigationTargetProvider,
    )

    if not (
        isinstance(inline_widget, ChildFieldIdentityProvider)
        and isinstance(inline_widget, ChildSubfieldNavigationTargetProvider)
    ):
        return None

    if tuple(display_path.split(".")) == inline_field_path:
        return InlineDataclassStructuralTarget(
            child_field_name=inline_field_path[-1],
            target=StructuralDescendantMaskTarget(inline_widget),
        )

    structural_path = StructuralFieldPath.from_display_path(display_path)
    if structural_path is not None:
        owner_parts = structural_path.owner_field_path.parts
        if (
            len(owner_parts) > len(inline_field_path)
            and owner_parts[: len(inline_field_path)] == inline_field_path
        ):
            child_field_name = owner_parts[len(inline_field_path)]
            child_identity = inline_widget.child_field_identity(child_field_name)
            target = inline_widget.child_subfield_navigation_target(
                child_identity,
                structural_path.relative_path,
            )
            if target is not None:
                return InlineDataclassStructuralTarget(
                    child_field_name=child_field_name,
                    target=target,
                )

    if owner_child_field_name is None:
        return None

    child_identity = inline_widget.child_field_identity(owner_child_field_name)
    target = inline_widget.child_subfield_navigation_target(
        child_identity,
        StructuralValuePath(),
    )
    if target is None:
        return None
    return InlineDataclassStructuralTarget(
        child_field_name=owner_child_field_name,
        target=target,
    )


@dataclass(frozen=True, slots=True)
class IsomorphicDataclassRowPathPolicy:
    """Map table columns to dataclass fields by declaration order."""

    row_value_type: type
    column_count: int

    def __post_init__(self) -> None:
        if not is_dataclass(self.row_value_type):
            raise TypeError(
                "IsomorphicDataclassRowPathPolicy requires a dataclass row type; "
                f"got {self.row_value_type!r}."
            )
        field_count = len(dataclass_fields(self.row_value_type))
        if self.column_count != field_count:
            raise ValueError(
                f"{self.row_value_type.__qualname__} has {field_count} fields "
                f"but the table declares {self.column_count} columns."
            )

    def relative_path_for_cell(
        self,
        row_index: int,
        column_index: int,
    ) -> StructuralValuePath:
        row_fields = dataclass_fields(self.row_value_type)
        if column_index < 0 or column_index >= len(row_fields):
            raise IndexError(
                f"Column {column_index} is outside {self.row_value_type.__name__}."
            )
        return (
            StructuralValuePath()
            .child_index(row_index)
            .child_field(row_fields[column_index].name)
        )


@dataclass(frozen=True, slots=True)
class EditableTableSemanticBinding:
    """Semantic binding between an owner child field and table cells."""

    owner_field_name: str
    row_path_policy: IsomorphicDataclassRowPathPolicy

    def relative_path_for_cell(
        self,
        row_index: int,
        column_index: int,
    ) -> StructuralValuePath:
        return self.row_path_policy.relative_path_for_cell(row_index, column_index)


def semantic_for_cell(
    semantic_index: ObjectStateSubfieldSemanticIndex,
    relative_path: StructuralValuePath,
) -> ObjectStateSubfieldSemantic | None:
    """Return the semantic leaf for a table cell path."""

    return semantic_index.leaf_for(relative_path)
