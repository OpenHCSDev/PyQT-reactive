"""Capacity-based responsive layout widgets for PyQt6."""

from enum import Enum

from PyQt6.QtCore import QSize, QTimer, Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pyqt_reactive.forms.layout_constants import (
    CURRENT_LAYOUT,
    ParameterFormLayoutConfig,
)


def _widget_required_width(widget: QWidget) -> int:
    """Return the minimum width at which a widget remains usable."""

    minimum_hint_width = max(0, widget.minimumSizeHint().width())
    if widget.sizePolicy().horizontalPolicy() is QSizePolicy.Policy.Preferred:
        hint_width = max(minimum_hint_width, widget.sizeHint().width())
    else:
        hint_width = minimum_hint_width
        if hint_width <= 0:
            hint_width = widget.sizeHint().width()
    return max(0, widget.minimumWidth(), hint_width)


def _widget_expands_horizontally(widget: QWidget) -> bool:
    """Return whether Qt declares the widget able to claim surplus row width."""

    return bool(
        widget.sizePolicy().expandingDirections() & Qt.Orientation.Horizontal
    )


def _required_row_width(
    widgets: list[QWidget],
    *,
    spacing: int,
    margins,
) -> int:
    """Return the horizontal capacity required by one widget row."""

    if not widgets:
        return margins.left() + margins.right()
    return (
        sum(_widget_required_width(widget) for widget in widgets)
        + spacing * (len(widgets) - 1)
        + margins.left()
        + margins.right()
    )


class ResponsiveRowLayoutMode(Enum):
    """Layout mode for two-row responsive widgets."""

    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"

    @property
    def uses_second_row(self) -> bool:
        return self is ResponsiveRowLayoutMode.VERTICAL


class ResponsiveTwoRowWidget(QWidget):
    """Widget that switches between 1-row (horizontal) and 2-row (vertical) layout."""
    
    def __init__(self, parent=None, layout_config=None):
        super().__init__(parent)
        self._layout_config = layout_config or CURRENT_LAYOUT
        self._layout_mode = ResponsiveRowLayoutMode.HORIZONTAL

        if not isinstance(self._layout_config, ParameterFormLayoutConfig):
            raise TypeError(
                "ResponsiveTwoRowWidget layout_config must be ParameterFormLayoutConfig, "
                f"got {type(self._layout_config).__name__}."
            )
        spacing = self._layout_config.parameter_row_spacing
        margins = self._layout_config.parameter_row_margins

        # Two rows
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(spacing)

        # Row 1: Always visible, contains left widgets + maybe right widgets
        self._row1 = QWidget()
        self._row1.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._row1_layout = QHBoxLayout(self._row1)
        self._row1_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._row1_layout.setContentsMargins(*margins)
        self._row1_layout.setSpacing(spacing)
        self._main_layout.addWidget(self._row1)

        # Row 2: Only for right widgets in vertical mode
        self._row2 = QWidget(self)  # Explicitly parent to self
        self._row2.setWindowFlags(Qt.WindowType.Widget)  # Ensure it's a widget, not a window
        self._row2.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._row2_layout = QHBoxLayout(self._row2)
        self._row2_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._row2_layout.setContentsMargins(*margins)
        self._row2_layout.setSpacing(spacing)
        self._main_layout.addWidget(self._row2)
        self._row2.hide()  # Start hidden in horizontal mode
        
        self._left_widgets: list[tuple[QWidget, int]] = []
        self._right_widgets: list[tuple[QWidget, int]] = []
        
        # Debounce timer
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._check_switch)
        
    def add_left_widget(self, widget: QWidget, stretch: int = 0) -> None:
        """Add widget to left side (stays in row1)."""
        self._left_widgets.append((widget, stretch))
        self._do_switch()
        self._timer.start(0)

    def add_right_widget(self, widget: QWidget, stretch: int = 0) -> None:
        """Add widget to right side (moves between row1 and row2)."""
        self._right_widgets.append((widget, stretch))
        self._do_switch()
        self._timer.start(0)

    def release_widgets(self, *widgets: QWidget) -> bool:
        """Release widget ownership so later reflows cannot reinsert them."""

        def retained(
            owned_widgets: list[tuple[QWidget, int]],
        ) -> list[tuple[QWidget, int]]:
            return [
                (owned_widget, stretch)
                for owned_widget, stretch in owned_widgets
                if all(owned_widget is not widget for widget in widgets)
            ]

        left_widgets = retained(self._left_widgets)
        right_widgets = retained(self._right_widgets)
        changed = (
            len(left_widgets) != len(self._left_widgets)
            or len(right_widgets) != len(self._right_widgets)
        )
        if not changed:
            return False

        self._left_widgets = left_widgets
        self._right_widgets = right_widgets
        self._do_switch()
        self._timer.start(0)
        return True

    def is_empty(self) -> bool:
        """Return whether this row owns no remaining presentation widgets."""

        return not self._left_widgets and not self._right_widgets

    def _check_switch(self) -> None:
        """Check if we need to switch layouts based on content width."""
        available_width = self.contentsRect().width()
        content_width = self._calculate_content_width()
        target_mode = (
            ResponsiveRowLayoutMode.HORIZONTAL
            if available_width <= 0 or content_width <= available_width
            else ResponsiveRowLayoutMode.VERTICAL
        )
        if target_mode is not self._layout_mode:
            self._layout_mode = target_mode
            self._do_switch()

    def _calculate_content_width(self) -> int:
        """Return the minimum width required to keep every widget on one row."""

        return _required_row_width(
            [widget for widget, _ in (*self._left_widgets, *self._right_widgets)],
            spacing=self._row1_layout.spacing(),
            margins=self._row1_layout.contentsMargins(),
        )

    @staticmethod
    def _clear_layout(layout: QHBoxLayout) -> None:
        while layout.count():
            layout.takeAt(0)

    def _add_right_widgets(self, layout: QHBoxLayout) -> None:
        has_expanding_widget = any(stretch > 0 for _, stretch in self._right_widgets)
        if self._right_widgets and not has_expanding_widget:
            layout.addStretch(1)
        for widget, stretch in self._right_widgets:
            if stretch > 0:
                layout.addWidget(widget, stretch)
            else:
                layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight)

    def _do_switch(self) -> None:
        """Actually perform the layout switch."""
        self._clear_layout(self._row1_layout)
        self._clear_layout(self._row2_layout)
        for widget, stretch in self._left_widgets:
            self._row1_layout.addWidget(widget, stretch)

        if not self._layout_mode.uses_second_row:
            self._row2.setVisible(False)
            self._add_right_widgets(self._row1_layout)
        else:
            self._add_right_widgets(self._row2_layout)
            self._row2.setVisible(True)

        self.updateGeometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._timer.start(0)

    def minimumSizeHint(self) -> QSize:
        """Return minimum size for layout calculations."""
        spacing = self._row1_layout.spacing()
        margins = self._row1_layout.contentsMargins()
        left_width = _required_row_width(
            [widget for widget, _ in self._left_widgets],
            spacing=spacing,
            margins=margins,
        )
        right_width = _required_row_width(
            [widget for widget, _ in self._right_widgets],
            spacing=spacing,
            margins=margins,
        )
        min_width = max(left_width, right_width)
        row1_height = self._row1.minimumSizeHint().height()
        if not self._layout_mode.uses_second_row:
            min_height = row1_height
        else:
            row2_height = self._row2.minimumSizeHint().height()
            main_spacing = self._main_layout.spacing()
            min_height = row1_height + main_spacing + row2_height
        
        return QSize(min_width, min_height)

    def sizeHint(self) -> QSize:
        """Return preferred size - only include visible content."""
        row1_width = self._row1.sizeHint().width()
        row2_width = self._row2.sizeHint().width() if self._layout_mode.uses_second_row else 0
        width = max(row1_width, row2_width)
        row1_height = self._row1.sizeHint().height()
        if not self._layout_mode.uses_second_row:
            height = row1_height
        else:
            row2_height = self._row2.sizeHint().height()
            main_spacing = self._main_layout.spacing()
            height = row1_height + main_spacing + row2_height
        
        return QSize(width, height)


class ResponsiveParameterRow(ResponsiveTwoRowWidget):
    """Row for PFM parameters."""
    
    def set_label(self, widget):
        widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        if isinstance(widget, QLabel):
            # Allow root-level field labels to wrap for better readability
            widget.setWordWrap(True)
        self.add_left_widget(widget, 0)
    
    def set_input(self, widget):
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.add_right_widget(widget, 1)
    
    def set_reset_button(self, widget):
        self.add_right_widget(widget, 0)
    
    def set_help_button(self, widget):
        self.add_right_widget(widget, 0)

class StagedWrapLayout(QWidget):
    def __init__(self, parent=None, spacing=4):
        super().__init__(parent)
        self._spacing = spacing
        self._groups = []
        self._stay_priority = []
        self._right_align_names = set()
        self._last_row1 = []
        self._last_row2 = []
        self._last_width = -1

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(spacing)

        self._row1_widget = QWidget(self)
        self._row1_widget.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self._row1_layout = QHBoxLayout(self._row1_widget)
        self._row1_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._row1_layout.setContentsMargins(0, 0, 0, 0)
        self._row1_layout.setSpacing(spacing)
        self._main_layout.addWidget(self._row1_widget)

        self._row2_widget = QWidget(self)
        self._row2_widget.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self._row2_layout = QHBoxLayout(self._row2_widget)
        self._row2_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._row2_layout.setContentsMargins(0, 0, 0, 0)
        self._row2_layout.setSpacing(spacing)
        self._main_layout.addWidget(self._row2_widget)
        self._row2_widget.hide()

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._update_layout)

    def set_groups(self, groups, stay_priority, right_align_names=None):
        self._groups = groups
        self._stay_priority = stay_priority
        self._right_align_names = set(right_align_names or [])
        self._update_layout()

    def refresh_layout(self):
        """Recompute capacity after a group's visible children change."""

        self._last_width = -1
        self._update_layout()
        self.updateGeometry()

    def resizeEvent(self, a0):
        super().resizeEvent(a0)
        self._resize_timer.start(50)

    def _clear_row(self, layout):
        while layout.count():
            layout.takeAt(0)

    def _row_width(self, names, widths):
        if not names:
            return 0
        total = 0
        for name in names:
            total += widths.get(name, 0)
        total += self._spacing * (len(names) - 1)
        return total

    def _update_layout(self):
        if not self._groups:
            return

        available = self.contentsRect().width()
        visual_order = [name for name, _ in self._groups]
        widths = {
            name: _widget_required_width(widget) for name, widget in self._groups
        }

        keep_names = []
        for name in self._stay_priority:
            candidate = keep_names + [name]
            if (
                not keep_names
                or available <= 0
                or self._row_width(candidate, widths) <= available
            ):
                keep_names.append(name)

        row1_names = [name for name in visual_order if name in keep_names]
        row2_names = [name for name in visual_order if name not in keep_names]

        if (
            available == self._last_width
            and row1_names == self._last_row1
            and row2_names == self._last_row2
        ):
            return

        self._last_row1 = list(row1_names)
        self._last_row2 = list(row2_names)
        self._last_width = available

        group_map = {name: widget for name, widget in self._groups}

        self._clear_row(self._row1_layout)
        row1_left = [name for name in row1_names if name not in self._right_align_names]
        row1_right = [name for name in row1_names if name in self._right_align_names]
        self._add_row_groups(
            self._row1_layout,
            row1_left,
            row1_right,
            group_map,
        )

        self._clear_row(self._row2_layout)
        row2_left = [name for name in row2_names if name not in self._right_align_names]
        row2_right = [name for name in row2_names if name in self._right_align_names]
        self._add_row_groups(
            self._row2_layout,
            row2_left,
            row2_right,
            group_map,
        )

        self._row2_widget.setVisible(bool(row2_names))

    @staticmethod
    def _add_row_groups(layout, left_names, right_names, group_map):
        for name in left_names:
            layout.addWidget(group_map[name])

        expanding_right_names = {
            name
            for name in right_names
            if _widget_expands_horizontally(group_map[name])
        }
        if right_names and not expanding_right_names:
            layout.addStretch(1)
        for name in right_names:
            widget = group_map[name]
            if name in expanding_right_names:
                layout.addWidget(widget, 1)
            else:
                layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight)
