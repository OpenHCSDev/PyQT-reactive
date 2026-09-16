"""
Shared QListWidget item delegate for rendering multiline items with grey preview text.

Single source of truth for list item rendering across PipelineEditor, PlateManager,
and other widgets that display items with preview labels.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import cast

from PyQt6.QtWidgets import (
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QStyle,
    QAbstractItemView,
    QListView,
)
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QPolygon
from PyQt6.QtCore import (
    Qt,
    QRect,
    QPoint,
    QPointF,
    QSize,
    QEvent,
    QPersistentModelIndex,
    QModelIndex,
    QObject,
)

from pyqt_reactive.widgets.shared.scope_color_utils import tint_color_perceptual
from pyqt_reactive.widgets.shared.config_tree_contracts import TreeFlashColorProvider
from pyqt_reactive.widgets.shared.scope_visual_config import (
    ScopeColorScheme,
    get_scope_visual_config,
)
from pyqt_reactive.widgets.shared.list_item_text_rendering import (
    StyledTextRenderer,
    PreparedTextLayout,
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
PREVIEW_WRAP_ROLE = Qt.ItemDataRole.UserRole + 16


class PreviewWrapMode(Enum):
    """Explicit row presentation; an absent model role inherits the view default."""

    HORIZONTAL = False
    WRAPPED = True

    @property
    def wrapped(self) -> bool:
        return self.value

    @classmethod
    def available(cls, view: QAbstractItemView, index: QModelIndex) -> bool:
        return (
            isinstance(view, QListView)
            and isinstance(view.itemDelegateForIndex(index), MultilinePreviewItemDelegate)
            and isinstance(index.data(LAYOUT_ROLE), StyledTextLayout)
        )

    @classmethod
    def for_index(cls, view: QListView, index: QModelIndex) -> "PreviewWrapMode":
        mode = index.data(PREVIEW_WRAP_ROLE)
        return cls(view.wordWrap()) if mode is None else mode

    @classmethod
    def interactive(cls, view: QAbstractItemView, index: QModelIndex) -> bool:
        return (
            cls.available(view, index)
            and view.isEnabled()
            and bool(index.flags() & Qt.ItemFlag.ItemIsEnabled)
        )

    @classmethod
    def toggle(cls, view: QAbstractItemView, index: QModelIndex) -> None:
        """Shared row mutation for native disclosure and structural UI actions."""
        if not cls.interactive(view, index):
            raise ValueError("This row does not expose an enabled preview disclosure.")
        view.model().setData(
            index, cls(not cls.for_index(cast(QListView, view), index).wrapped), PREVIEW_WRAP_ROLE
        )
        view.itemDelegateForIndex(index).sizeHintChanged.emit(index)
        view.doItemsLayout()
        view.viewport().update()


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

    TEXT_INSET_X = 5
    TEXT_INSET_Y = 3
    MINIMUM_ROW_HEIGHT = 29
    DISCLOSURE_WIDTH = 16

    def __init__(
        self,
        name_color: QColor,
        preview_color: QColor,
        selected_text_color: QColor,
        parent: QListView,
        manager: TreeFlashColorProvider | None = None,
    ):
        """Initialize delegate with color scheme.

        Args:
            name_color: Color for normal text lines
            preview_color: Color for preview text lines (grey)
            selected_text_color: Color for text when item is selected
            parent: Parent widget (QListWidget)
            manager: Flash-color provider that owns delegate paint acknowledgements
        """
        super().__init__(parent)
        self.name_color = name_color
        self.preview_color = preview_color
        self.selected_text_color = selected_text_color
        self._manager = manager
        self._text_metric_cache = TextMetricCache()
        self._text_renderer = StyledTextRenderer(self._text_metric_cache)
        self._pressed_disclosure = QPersistentModelIndex()
        parent.viewport().installEventFilter(self)
        # NOTE: Flash rendering moved to WindowFlashOverlay for O(1) performance

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        """Paint the item with multiline support and flash behind text."""
        # Prepare a copy to let style draw backgrounds, hover, selection, borders, etc.
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        # A wrapped row owns one viewport-anchored paint frame for native style,
        # flash/background, marker and text, independent of other rows' overflow.
        opt.rect = self._row_rect(option, index)

        # Capture text and prevent default text draw
        opt.text = ""

        # Calculate border inset (used for background and flash)
        scheme = index.data(SCOPE_SCHEME_ROLE)
        border_inset = 0
        layers = None
        if isinstance(scheme, ScopeColorScheme):
            layers = scheme.step_border_layers
            if layers:
                border_inset = sum(layer[0] for layer in layers)
        content_rect = opt.rect.adjusted(border_inset, border_inset, -border_inset, -border_inset)

        # Scope-based background: match border colors (only when not selected)
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if not is_selected:
            self._paint_scope_background(painter, content_rect, scheme, layers)

        # Flash effect - drawn BEHIND text but inside borders
        object_state_path = index.data(OBJECT_STATE_PATH_ROLE)
        painted_flash_alpha = None
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
                painted_flash_alpha = flash_color.alpha()

        # Let the style draw selection, hover, borders
        self.parent().style().drawControl(
            QStyle.ControlElement.CE_ItemViewItem, opt, painter, self.parent()
        )

        # Now draw text manually with custom colors
        painter.save()

        leading_marker = index.data(LEADING_MARKER_ROLE)
        text_rect = opt.rect
        if isinstance(leading_marker, ListItemLeadingMarker):
            self._paint_leading_marker(
                painter,
                text_rect,
                leading_marker,
                is_selected=is_selected,
            )
        try:
            painter.setClipRect(text_rect)
            if self._has_disclosure(index):
                disclosure = QStyleOptionViewItem(opt)
                disclosure.rect = self.disclosure_rect(opt, index)
                disclosure.state = QStyle.StateFlag.State_Children
                if PreviewWrapMode.interactive(self.parent(), index):
                    disclosure.state |= QStyle.StateFlag.State_Enabled
                if self._row_wraps(index):
                    disclosure.state |= QStyle.StateFlag.State_Open
                self.parent().style().drawPrimitive(
                    QStyle.PrimitiveElement.PE_IndicatorBranch, disclosure, painter, self.parent()
                )
            self._prepared_text(opt, index).paint(
                painter,
                QPointF(
                    text_rect.left() + self.TEXT_INSET_X + self._text_gutter(index),
                    text_rect.top() + self.TEXT_INSET_Y,
                ),
            )
        finally:
            painter.restore()

        if scheme is not None:
            self._paint_border_layers(painter, opt.rect, scheme)
        if painted_flash_alpha is not None:
            self._manager.acknowledge_flash_paint(object_state_path, self.parent(), painted_flash_alpha)

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

    def _paint_scope_background(
        self, painter: QPainter, content_rect: QRect, scheme, layers
    ) -> None:
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

    def _paint_checkerboard_flash(
        self, painter: QPainter, content_rect: QRect, flash_color: QColor
    ) -> None:
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

    def _marker_gutter(self, index) -> int:
        if isinstance(index.data(LEADING_MARKER_ROLE), ListItemLeadingMarker):
            return get_scope_visual_config().LIST_ITEM_LEADING_MARKER_GUTTER_WIDTH_PX
        return 0

    def _has_disclosure(self, index: QModelIndex) -> bool:
        return PreviewWrapMode.available(self.parent(), index)

    def _text_gutter(self, index: QModelIndex) -> int:
        return self._marker_gutter(index) + (
            self.DISCLOSURE_WIDTH if self._has_disclosure(index) else 0
        )

    def _row_wraps(self, index: QModelIndex) -> bool:
        return PreviewWrapMode.for_index(self.parent(), index).wrapped

    def _row_rect(self, option: QStyleOptionViewItem, index: QModelIndex) -> QRect:
        """One row frame for native decoration, flash, content and disclosure hits."""
        rect = QRect(option.rect)
        if self._row_wraps(index):
            rect.setLeft(0)
            rect.setWidth(self.parent().viewport().width())
        return rect

    def disclosure_rect(self, option: QStyleOptionViewItem, index: QModelIndex) -> QRect:
        """One first-line target shared by native painting and mouse handling."""
        if not self._has_disclosure(index):
            return QRect()
        text_rect = self._row_rect(option, index)
        prepared = self._prepared_text(option, index)
        first_line_height = prepared.paragraphs[0].lineAt(0).height()
        return QRect(
            text_rect.left() + self.TEXT_INSET_X + self._marker_gutter(index),
            text_rect.top() + self.TEXT_INSET_Y,
            self.DISCLOSURE_WIDTH,
            max(1, round(first_line_height)),
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        """Consume disclosure clicks before QListView selection/drag/activation."""
        if event.type() not in {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.MouseMove,
        }:
            return super().eventFilter(watched, event)
        view = self.parent()
        if watched is not view.viewport():
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.MouseMove and self._pressed_disclosure.isValid():
            return True
        if event.button() != Qt.MouseButton.LeftButton:
            return super().eventFilter(watched, event)
        index = view.indexAt(event.position().toPoint())
        option = QStyleOptionViewItem()
        option.initFrom(view)
        option.font = view.font()
        option.rect = view.visualRect(index)
        hit = PreviewWrapMode.interactive(view, index) and self.disclosure_rect(
            option, index
        ).contains(event.position().toPoint())
        if event.type() != QEvent.Type.MouseButtonRelease:
            if hit:
                self._pressed_disclosure = QPersistentModelIndex(index)
            return hit
        pressed = self._pressed_disclosure
        self._pressed_disclosure = QPersistentModelIndex()
        if hit and pressed == index:
            PreviewWrapMode.toggle(view, index)
        return pressed.isValid()

    def _prepared_text(self, option: QStyleOptionViewItem, index) -> PreparedTextLayout:
        """Use identical fonts, field markers and available width in both passes."""
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        font = QFont(opt.font)
        font.setStrikeOut(bool(index.data(Qt.ItemDataRole.UserRole + 1)))
        font.setUnderline(False)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        layout = index.data(LAYOUT_ROLE)
        width = None
        if self._row_wraps(index):
            width = max(
                1,
                self.parent().viewport().width() - self.TEXT_INSET_X * 2 - self._text_gutter(index),
            )
        return self._text_renderer.prepare(
            layout if isinstance(layout, StyledTextLayout) else opt.text,
            TextPaintContext(
                dirty_fields=index.data(DIRTY_FIELDS_ROLE) or set(),
                sig_diff_fields=index.data(SIG_DIFF_FIELDS_ROLE) or set(),
                base_font=font,
                name_color=self.selected_text_color if selected else self.name_color,
                preview_color=self.selected_text_color if selected else self.preview_color,
            ),
            width,
        )

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        """Measure the exact glyph layout painted in this viewport."""
        prepared = self._prepared_text(option, index)
        width = prepared.size.width() + self.TEXT_INSET_X * 2 + self._text_gutter(index)
        if self._row_wraps(index):
            width = self.parent().viewport().width()
        return QSize(
            width,
            max(self.MINIMUM_ROW_HEIGHT, prepared.size.height() + self.TEXT_INSET_Y * 2),
        )
