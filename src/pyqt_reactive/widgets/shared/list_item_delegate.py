"""
Shared QListWidget item delegate for rendering multiline items with grey preview text.

Single source of truth for list item rendering across PipelineEditor, PlateManager,
and other widgets that display items with preview labels.
"""

import logging
from dataclasses import dataclass

from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyle
from PyQt6.QtGui import QPainter, QColor, QFont, QFontMetrics, QPen, QPolygon
from PyQt6.QtCore import Qt, QRect, QPoint

from pyqt_reactive.widgets.shared.scope_color_utils import tint_color_perceptual
from pyqt_reactive.widgets.shared.scope_visual_config import (
    ScopeColorScheme,
    get_scope_visual_config,
)
from pyqt_reactive.widgets.shared.list_item_text_rendering import (
    StyledTextRenderer,
    StyledTextSizeCalculator,
    TextMetricCache,
    TextPaintContext,
)
from pyqt_reactive.widgets.shared.styled_text_layout import (
    Segment,
    StyledText,
    StyledTextLayout,
    join_segments,
)

# Custom data role for scope color scheme (must match manager)
SCOPE_SCHEME_ROLE = Qt.ItemDataRole.UserRole + 10
# ObjectState path role - stores the row scope/path used for flash color lookup
OBJECT_STATE_PATH_ROLE = Qt.ItemDataRole.UserRole + 11
# Per-field styling roles
LAYOUT_ROLE = Qt.ItemDataRole.UserRole + 12  # StyledTextLayout for structured rendering
DIRTY_FIELDS_ROLE = Qt.ItemDataRole.UserRole + 13  # Set[str] - dotted paths of dirty fields
SIG_DIFF_FIELDS_ROLE = Qt.ItemDataRole.UserRole + 14  # Set[str] - dotted paths of sig-diff fields
LEADING_MARKER_ROLE_OFFSET = 15
LEADING_MARKER_ROLE = Qt.ItemDataRole.UserRole + LEADING_MARKER_ROLE_OFFSET  # ListItemLeadingMarker

# Backwards compat alias
SEGMENTS_ROLE = LAYOUT_ROLE

# Border patterns matching ScopedBorderMixin
BORDER_PATTERNS = {
    "solid": (Qt.PenStyle.SolidLine, None),
    "dashed": (Qt.PenStyle.DashLine, [8, 6]),
    "dotted": (Qt.PenStyle.DotLine, [2, 6]),
    "dashdot": (Qt.PenStyle.DashDotLine, [8, 4, 2, 4]),
}

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ListItemLeadingMarker:
    """Declarative leading marker for externally owned row state."""

    color: QColor | None = None


class MultilinePreviewItemDelegate(QStyledItemDelegate):
    """Custom delegate to render multiline items with grey preview text.

    TRUE O(1) ARCHITECTURE: Flash effects are rendered by WindowFlashOverlay.
    This delegate does NOT paint flash backgrounds - window overlay handles all flash
    rendering in a single paintEvent for O(1) per window.

    Supports:
    - Multiline text rendering (automatic height calculation)
    - Grey preview text for lines containing specific markers
    - Proper hover/selection/border rendering
    - Configurable colors for normal/preview/selected text
    """

    def __init__(self, name_color: QColor, preview_color: QColor, selected_text_color: QColor,
                 parent=None, manager=None):
        """Initialize delegate with color scheme.

        Args:
            name_color: Color for normal text lines
            preview_color: Color for preview text lines (grey)
            selected_text_color: Color for text when item is selected
            parent: Parent widget (QListWidget)
            manager: Manager widget (unused - kept for API compat)
        """
        super().__init__(parent)
        self.name_color = name_color
        self.preview_color = preview_color
        self.selected_text_color = selected_text_color
        self._manager = manager
        self._text_metric_cache = TextMetricCache()
        self._text_renderer = StyledTextRenderer(self._text_metric_cache)
        self._size_calculator = StyledTextSizeCalculator(self._text_metric_cache)
        # NOTE: Flash rendering moved to WindowFlashOverlay for O(1) performance

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        """Paint the item with multiline support and flash behind text."""
        from PyQt6.QtGui import QFont, QFontMetrics

        # Prepare a copy to let style draw backgrounds, hover, selection, borders, etc.
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        # Capture text and prevent default text draw
        text = opt.text or ""
        opt.text = ""

        # Calculate border inset (used for background and flash)
        scheme = index.data(SCOPE_SCHEME_ROLE)
        border_inset = 0
        layers = None
        if isinstance(scheme, ScopeColorScheme):
            layers = scheme.step_border_layers
            if layers:
                border_inset = sum(layer[0] for layer in layers)
        content_rect = option.rect.adjusted(border_inset, border_inset, -border_inset, -border_inset)

        # Scope-based background: match border colors (only when not selected)
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if not is_selected:
            self._paint_scope_background(painter, content_rect, scheme, layers)

        # Flash effect - drawn BEHIND text but inside borders
        object_state_path = index.data(OBJECT_STATE_PATH_ROLE)
        if object_state_path and self._manager is not None:
            flash_color = self._manager.get_flash_color_for_object_state_path(object_state_path)
            if flash_color and flash_color.alpha() > 0:
                if isinstance(scheme, ScopeColorScheme):
                    base_rgb = scheme.base_color_rgb
                    item_layers = scheme.step_border_layers
                    if base_rgb and item_layers:
                        _, tint_idx, _ = (item_layers[0] + ("solid",))[:3]
                        computed_color = tint_color_perceptual(base_rgb, tint_idx).darker(120)
                        computed_color.setAlpha(flash_color.alpha())
                        flash_color = computed_color

                if layers and len(layers) > 1:
                    self._paint_checkerboard_flash(painter, content_rect, flash_color)
                else:
                    painter.fillRect(content_rect, flash_color)

        # Let the style draw selection, hover, borders
        self.parent().style().drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, self.parent())

        # Now draw text manually with custom colors
        painter.save()

        is_disabled = index.data(Qt.ItemDataRole.UserRole + 1) or False

        # Get structured layout - no string parsing needed!
        layout = index.data(LAYOUT_ROLE)
        dirty_fields = index.data(DIRTY_FIELDS_ROLE) or set()
        sig_diff_fields = index.data(SIG_DIFF_FIELDS_ROLE) or set()
        leading_marker = index.data(LEADING_MARKER_ROLE)

        base_font = QFont(option.font)
        base_font.setStrikeOut(is_disabled)
        base_font.setUnderline(False)

        fm = QFontMetrics(base_font)
        line_height = fm.height()
        text_rect = option.rect
        visual_config = get_scope_visual_config()
        marker_gutter_width = (
            visual_config.LIST_ITEM_LEADING_MARKER_GUTTER_WIDTH_PX
            if isinstance(leading_marker, ListItemLeadingMarker)
            else 0
        )
        if isinstance(leading_marker, ListItemLeadingMarker):
            self._paint_leading_marker(
                painter,
                text_rect,
                leading_marker,
                is_selected=is_selected,
            )
        x_start = text_rect.left() + 5 + marker_gutter_width
        y_offset = text_rect.top() + fm.ascent() + 3

        try:
            if isinstance(layout, StyledTextLayout):
                name_color = self.selected_text_color if is_selected else self.name_color
                preview_color = self.selected_text_color if is_selected else self.preview_color
                self._text_renderer.paint_layout(
                    painter,
                    layout,
                    TextPaintContext(
                        dirty_fields=dirty_fields,
                        sig_diff_fields=sig_diff_fields,
                        base_font=base_font,
                        name_color=name_color,
                        preview_color=preview_color,
                    ),
                    x_start,
                    y_offset,
                    line_height,
                )
            else:
                self._paint_plain_text_fallback(painter, text, base_font, x_start, y_offset, is_selected)
        finally:
            painter.restore()

        if scheme is not None:
            self._paint_border_layers(painter, option.rect, scheme)

    def _paint_leading_marker(
        self,
        painter: QPainter,
        rect: QRect,
        marker: ListItemLeadingMarker,
        *,
        is_selected: bool,
    ) -> None:
        """Paint a strong row-level marker without encoding its domain meaning."""
        visual_config = get_scope_visual_config()
        marker_color = (
            QColor(marker.color)
            if marker.color is not None
            else QColor(*visual_config.LIST_ITEM_LEADING_MARKER_COLOR_RGB)
        )
        if is_selected:
            marker_color = QColor(self.selected_text_color)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(marker_color)

        stripe_top_margin = visual_config.LIST_ITEM_LEADING_MARKER_STRIPE_TOP_MARGIN_PX
        stripe = QRect(
            rect.left() + visual_config.LIST_ITEM_LEADING_MARKER_STRIPE_LEFT_PX,
            rect.top() + stripe_top_margin,
            visual_config.LIST_ITEM_LEADING_MARKER_STRIPE_WIDTH_PX,
            max(0, rect.height() - (stripe_top_margin * 2)),
        )
        stripe_radius = visual_config.LIST_ITEM_LEADING_MARKER_STRIPE_RADIUS_PX
        painter.drawRoundedRect(stripe, stripe_radius, stripe_radius)

        mid_y = rect.center().y()
        triangle_left = rect.left() + visual_config.LIST_ITEM_LEADING_MARKER_TRIANGLE_LEFT_PX
        triangle_width = visual_config.LIST_ITEM_LEADING_MARKER_TRIANGLE_WIDTH_PX
        triangle_half_height = visual_config.LIST_ITEM_LEADING_MARKER_TRIANGLE_HALF_HEIGHT_PX
        triangle = QPolygon(
            [
                QPoint(triangle_left, mid_y - triangle_half_height),
                QPoint(triangle_left, mid_y + triangle_half_height),
                QPoint(triangle_left + triangle_width, mid_y),
            ]
        )
        painter.drawPolygon(triangle)
        painter.restore()

    def _paint_plain_text_fallback(
        self,
        painter: QPainter,
        text: str,
        base_font: QFont,
        x_start: int,
        y_offset: int,
        is_selected: bool,
    ) -> None:
        """Paint rows that intentionally do not carry a structured text layout."""
        painter.setFont(base_font)
        painter.setPen(self.selected_text_color if is_selected else self.name_color)
        painter.drawText(x_start, y_offset, text)

    def _paint_scope_background(self, painter: QPainter, content_rect: QRect, scheme, layers) -> None:
        """Paint background matching border colors.

        If single layer: solid color matching border.
        If multiple layers: grid pattern of layer colors.
        """
        from pyqt_reactive.widgets.shared.scope_visual_config import ScopeVisualConfig

        if not isinstance(scheme, ScopeColorScheme):
            return

        base_rgb = scheme.base_color_rgb
        if not base_rgb:
            return

        opacity = ScopeVisualConfig.STEP_ITEM_BG_OPACITY

        if not layers or len(layers) == 1:
            # Single layer: solid background matching first layer color
            if layers:
                _, tint_idx, _ = (layers[0] + ("solid",))[:3]
            else:
                tint_idx = 1  # default to middle tint
            color = tint_color_perceptual(base_rgb, tint_idx)
            color.setAlphaF(opacity)
            painter.fillRect(content_rect, color)
        else:
            # Multiple layers: draw checkerboard with 2 perceptually distinct lightness levels
            cell_size = 8  # pixels per grid cell
            painter.save()
            painter.setClipRect(content_rect)

            # Use dark (tint 0) and light (tint 2) variants - no hue shift
            color1 = tint_color_perceptual(base_rgb, 0)  # dark
            color2 = tint_color_perceptual(base_rgb, 2)  # light
            color1.setAlphaF(opacity)
            color2.setAlphaF(opacity)

            self._paint_checkerboard_cells(painter, content_rect, color1, color2, cell_size)

            painter.restore()

    def _paint_checkerboard_flash(self, painter: QPainter, content_rect: QRect, flash_color: QColor) -> None:
        """Paint flash effect as checkerboard for multi-layer items."""
        cell_size = 8
        painter.save()
        painter.setClipRect(content_rect)

        # Create light/dark variants of flash color
        base_alpha = flash_color.alphaF()
        color1 = QColor(flash_color)
        color2 = QColor(flash_color)
        color1.setAlphaF(base_alpha * 0.6)  # darker cells
        color2.setAlphaF(base_alpha * 1.4)  # lighter cells (capped by Qt)

        self._paint_checkerboard_cells(painter, content_rect, color1, color2, cell_size)

        painter.restore()

    def _paint_checkerboard_cells(
        self,
        painter: QPainter,
        content_rect: QRect,
        color1: QColor,
        color2: QColor,
        cell_size: int,
    ) -> None:
        """Paint alternating clipped cells with caller-provided colors."""
        for x in range(content_rect.left(), content_rect.right(), cell_size):
            for y in range(content_rect.top(), content_rect.bottom(), cell_size):
                is_even = ((x // cell_size) + (y // cell_size)) % 2 == 0
                cell_rect = QRect(x, y, cell_size, cell_size)
                painter.fillRect(cell_rect.intersected(content_rect), color1 if is_even else color2)

    def _paint_border_layers(self, painter: QPainter, rect: QRect, scheme) -> None:
        """Paint layered borders matching window border style.

        Uses same algorithm as ScopedBorderMixin._paint_border_layers() to ensure
        list items have identical borders to their corresponding windows.
        """
        if not isinstance(scheme, ScopeColorScheme):
            return

        layers = scheme.step_border_layers
        base_rgb = scheme.base_color_rgb

        if not layers or not base_rgb:
            # Fallback: simple border using orchestrator border color
            border_color = scheme.to_qcolor_orchestrator_border()
            painter.save()
            pen = QPen(border_color, 2)
            pen.setStyle(Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.drawRect(rect.adjusted(1, 1, -2, -2))
            painter.restore()
            return

        # Paint layered borders (same logic as ScopedBorderMixin)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        inset = 0
        for layer in layers:
            width, tint_idx, pattern = (layer + ("solid",))[:3]
            color = tint_color_perceptual(base_rgb, tint_idx).darker(120)

            pen = QPen(color, width)
            style, dash_pattern = BORDER_PATTERNS.get(pattern, BORDER_PATTERNS["solid"])
            pen.setStyle(style)
            if dash_pattern:
                pen.setDashPattern(dash_pattern)

            offset = int(inset + width / 2)
            painter.setPen(pen)
            painter.drawRect(rect.adjusted(offset, offset, -offset - 1, -offset - 1))
            inset += width

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> 'QSize':
        """Calculate size hint based on layout structure."""
        # Get structured layout data
        layout = index.data(LAYOUT_ROLE)
        if layout is not None:
            return self._size_calculator.from_layout(layout, option.font)
        else:
            # Fallback to text-based sizing
            text = index.data(Qt.ItemDataRole.DisplayRole) or ""
            return self._size_calculator.from_text(text, option.font)
