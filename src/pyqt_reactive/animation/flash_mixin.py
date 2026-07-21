"""Unified visual update mixin for PyQt widgets.

GAME ENGINE ARCHITECTURE (TRUE O(1) PER WINDOW):
- ONE WindowFlashOverlay per top-level window renders ALL flash effects
- ALL element types (groupboxes, tree items, list items) register with it
- Single paintEvent draws ALL flash rectangles regardless of element count/type
- Scales O(1) per window, O(k) per flashing element, regardless of total elements

BATCH COLOR COMPUTATION:
- Global 60fps coordinator pre-computes ALL colors in ONE pass
- Overlays just do O(1) dict lookups during paintEvent
- Total work: O(k) per tick where k = number of flashing elements

ALGEBRAIC SIMPLIFICATIONS (OpenHCS-style):
FIX 1: Eliminated global/local flash duality
  - Before: 2 parallel systems (_flash_start_times + _window_flash_start_times)
  - After: 1 unified system (all keys auto-scoped via _get_scoped_flash_key)
  - Reduction: 2 → 1 (50% simpler, 100+ lines removed)

FIX 2: Simplified dirty tracking
  - Before: 4 prev-color dicts, 30 lines of comparison logic
  - After: 0 dicts, direct dict comparison (Qt batches update() calls anyway)
  - Reduction: Removed complex dirty flag system (30 lines → 2 lines)

FIX 3: Unified geometry cache
  - Before: 2 separate caches (_scroll_area_clip_rects + _cached_element_rects)
  - After: 1 OverlayGeometryCache dataclass with single invalidation point
  - Reduction: Single invalidate() method, clearer ownership
"""

import logging
import time
from dataclasses import dataclass, field
from functools import partial
from typing import Dict, Iterable, List, Optional, Set, Callable, Any, Tuple, TYPE_CHECKING
from weakref import WeakValueDictionary
import re
from objectstate import DottedFieldPath
from PyQt6.QtCore import (
    QCoreApplication,
    QObject,
    QThread,
    QTimer,
    Qt,
    QRect,
    QRectF,
    QSize,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyle,
    QStyleOptionButton,
    QTableWidget,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QWidget,
)
from PyQt6.QtGui import QColor, QPainter, QRegion, QPainterPath
from PyQt6 import sip

from objectstate.time_travel_profile import TimeTravelProfiler
from pyqt_reactive.animation.flash_config import FlashConfig, get_flash_config
from pyqt_reactive.animation.flash_trace import flash_trace
from pyqt_reactive.forms.layout_constants import default_container_corner_radius_px

# Cache for extracted widget corner radii (widget_id -> radius)
_corner_radius_cache: Dict[int, float] = {}

# Regex to extract border-radius from stylesheet (handles px, em, or bare numbers)
_BORDER_RADIUS_RE = re.compile(r'border-radius\s*:\s*(\d+(?:\.\d+)?)\s*(?:px)?', re.IGNORECASE)

# PERF: Pre-compiled regex for step token detection (avoids per-tick compilation)
_STEP_TOKEN_RE = re.compile(r"^[a-z]+step_\d+$", re.IGNORECASE)


def get_widget_corner_radius(widget: QWidget) -> float:
    """Extract corner radius from widget's stylesheet, with caching.

    Searches the widget and its ancestors for border-radius in stylesheets.
    Returns 0 if no border-radius found (sharp corners).
    """
    widget_id = id(widget)
    if widget_id in _corner_radius_cache:
        return _corner_radius_cache[widget_id]

    # Search widget and ancestors for stylesheet with border-radius
    current = widget
    radius = 0.0
    while current is not None:
        stylesheet = current.styleSheet()
        if stylesheet:
            match = _BORDER_RADIUS_RE.search(stylesheet)
            if match:
                radius = float(match.group(1))
                break
        current = current.parentWidget()

    _corner_radius_cache[widget_id] = radius
    return radius


def invalidate_corner_radius_cache(widget: Optional[QWidget] = None) -> None:
    """Invalidate corner radius cache for a widget or all widgets."""
    if widget is None:
        _corner_radius_cache.clear()
    else:
        _corner_radius_cache.pop(id(widget), None)


def queue_visual_frame_callback(owner: QObject, callback: Callable[[], None]) -> None:
    """Run a coalesced owner callback on the shared visual frame coordinator."""

    _GlobalFlashCoordinator.get().queue_visual_frame_callback(owner, callback)


def active_visual_frame_work_count() -> int:
    """Return pending or active visual-frame work known to the shared coordinator."""

    coordinator = _GlobalFlashCoordinator._instance
    if coordinator is None:
        return 0
    return coordinator.active_visual_frame_work_count()

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QGroupBox, QTreeWidget, QListWidget
    from pyqt_reactive.widgets.structural_table import StructuralTableCellTarget

logger = logging.getLogger(__name__)

# Declarative mapping: hierarchy level -> ScopeColorScheme -> QColor (or None for default flash color)
SCOPE_LEVEL_COLOR_SELECTORS: Dict[int, Callable[[Any], Optional[QColor]]] = {
    0: lambda scheme: None,  # Level 0: use default flash color (config base)
    1: lambda scheme: scheme.to_qcolor_orchestrator_border(),
    2: lambda scheme: scheme.to_qcolor_step_window_border(),
}


# ==================== CIRCULAR PALETTE FLASH COLORS ====================
# Pre-computed WCAG AA compliant color palette for flash animations.
# 6 base hues × 3 variants = 18 total colors, cycling deterministically.

def _ensure_wcag_compliant(
    color_rgb: Tuple[int, int, int],
    background: Tuple[int, int, int] = (255, 255, 255),
    min_ratio: float = 4.5,
) -> Tuple[int, int, int]:
    """Adjust color to meet WCAG AA contrast against background."""
    import colorsys
    try:
        from wcag_contrast_ratio.contrast import rgb as wcag_rgb

        color_01 = tuple(c / 255.0 for c in color_rgb)
        bg_01 = tuple(c / 255.0 for c in background)
        current_ratio = wcag_rgb(color_01, bg_01)
        if current_ratio >= min_ratio:
            return color_rgb

        h, s, v = colorsys.rgb_to_hsv(*color_01)
        while v > 0.1:
            v *= 0.9
            adjusted_rgb_01 = colorsys.hsv_to_rgb(h, s, v)
            ratio = wcag_rgb(adjusted_rgb_01, bg_01)
            if ratio >= min_ratio:
                return tuple(int(c * 255) for c in adjusted_rgb_01)  # type: ignore
        return tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h, s, 0.1))  # type: ignore
    except ImportError:
        # wcag-contrast-ratio not installed, return color unchanged
        return color_rgb


def _extract_orchestrator_scope(scope_id: Optional[str]) -> Optional[str]:
    """Extract orchestrator portion from scope_id."""
    if scope_id is None:
        return None
    if "::" in scope_id:
        return scope_id.split("::", 1)[0]
    return scope_id


def _generate_flash_palette() -> List[Tuple[int, int, int]]:
    """Generate WCAG AA compliant flash color palette.

    Returns 18 RGB tuples: 6 base hues × 3 variants (normal, dark, light).
    All colors guaranteed to have ≥4.5:1 contrast against white background.
    """
    import colorsys

    palette = []
    base_hues = [0, 60, 120, 180, 240, 300]  # Red, Yellow, Green, Cyan, Blue, Magenta

    # 3 variants per hue: normal, dark, light
    variants = [
        (0.70, 0.60),  # Normal: 70% saturation, 60% value
        (0.80, 0.45),  # Dark: 80% saturation, 45% value
        (0.50, 0.75),  # Light: 50% saturation, 75% value
    ]

    for hue in base_hues:
        for saturation, value in variants:
            # Convert HSV to RGB
            r, g, b = colorsys.hsv_to_rgb(hue / 360.0, saturation, value)
            rgb = (int(r * 255), int(g * 255), int(b * 255))

            # Ensure WCAG AA compliance (4.5:1 contrast against white)
            rgb = _ensure_wcag_compliant(rgb, background=(255, 255, 255))
            palette.append(rgb)

    return palette


# Pre-computed palette (generated once at module load)
_FLASH_COLOR_PALETTE_RGB: List[Tuple[int, int, int]] = _generate_flash_palette()


def get_flash_color_from_palette(scope_id: str, alpha: int = 255, use_parent_scope: bool = True) -> QColor:
    """Get flash color from circular palette based on scope_id.

    Args:
        scope_id: Scope identifier (e.g., "plate::config_field")
        alpha: Alpha channel (0-255)
        use_parent_scope: If True, hash only parent scope (plate path) so all elements
                         in same plate get same color. If False, hash full scope_id.

    Returns:
        QColor from pre-computed WCAG-compliant palette
    """
    import hashlib

    # Extract parent scope (plate path) if requested
    # This ensures all elements in same plate get same color
    scope_to_hash = _extract_orchestrator_scope(scope_id) if use_parent_scope else scope_id
    if scope_to_hash is None:
        scope_to_hash = scope_id

    # Hash scope to deterministic index in palette
    hash_bytes = hashlib.md5(scope_to_hash.encode()).digest()
    index = int.from_bytes(hash_bytes[:2], byteorder="big") % len(_FLASH_COLOR_PALETTE_RGB)

    r, g, b = _FLASH_COLOR_PALETTE_RGB[index]
    return QColor(r, g, b, alpha)


def _base_color(config: FlashConfig) -> QColor:
    r, g, b = config.base_color_rgb
    return QColor(r, g, b)


def _full_flash_color(config: FlashConfig) -> QColor:
    r, g, b = config.base_color_rgb
    return QColor(r, g, b, config.flash_alpha)


def get_flash_color(
    opacity: float = 1.0,
    config: Optional[FlashConfig] = None,
    base_color: Optional[QColor] = None,
) -> QColor:
    """Get the shared flash QColor with optional opacity (0.0-1.0)."""
    cfg = config or get_flash_config()
    if base_color is not None:
        color = QColor(base_color)
        color.setAlpha(int(cfg.flash_alpha * opacity))
        return color
    if opacity >= 1.0:
        return _full_flash_color(cfg)
    color = _base_color(cfg)
    color.setAlpha(int(cfg.flash_alpha * opacity))
    return color


def compute_flash_color_at_time(
    start_time: float,
    now: float,
    config: Optional[FlashConfig] = None,
    base_color: Optional[QColor] = None,
) -> Optional[QColor]:
    """Compute flash color based on elapsed time. Returns None if animation complete.

    PAINT-TIME COMPUTATION: Called during paint, not during timer tick.
    This moves O(n) color computation from timer to paint (which Qt batches).
    """
    cfg = config or get_flash_config()
    fade_in_s = cfg.fade_in_s
    hold_s = cfg.hold_s
    fade_out_s = cfg.fade_out_s
    total_duration_s = fade_in_s + hold_s + fade_out_s

    elapsed = now - start_time

    if elapsed < 0:
        return None  # Not started yet
    elif elapsed >= total_duration_s:
        return None  # Animation complete
    elif elapsed < fade_in_s:
        # Fade in: 0 → full alpha
        t = elapsed / fade_in_s
        t = t * (2 - t)  # OutQuad easing
        alpha = int(cfg.flash_alpha * t)
        color = QColor(base_color) if base_color is not None else _base_color(cfg)
        color.setAlpha(alpha)
        return color
    elif elapsed < fade_in_s + hold_s:
        if base_color is not None:
            color = QColor(base_color)
            color.setAlpha(cfg.flash_alpha)
            return color
        return _full_flash_color(cfg)
    else:
        # Fade out: full → 0
        fade_elapsed = elapsed - fade_in_s - hold_s
        t = fade_elapsed / fade_out_s
        # InOutCubic easing
        if t < 0.5:
            t = 4 * t * t * t
        else:
            t = 1 - pow(-2 * t + 2, 3) / 2
        alpha = int(cfg.flash_alpha * (1 - t))
        color = QColor(base_color) if base_color is not None else _base_color(cfg)
        color.setAlpha(alpha)
        return color


# ==================== FLASH ELEMENT REGISTRATION ====================
# Unified element representation for groupboxes, tree items, list items

FlashGeometry = Tuple[Optional[QRect], float]

@dataclass
class OverlayGeometryCache:
    """Unified cache for all overlay geometry calculations.

    FIX 3: Single cache object with single invalidation point.
    Replaces separate scroll_area + element caches.
    """
    valid: bool = False
    clip_rects_valid: bool = False
    scroll_clip_rects: List[QRect] = field(default_factory=list)
    element_rects: Dict[str, List[Optional[FlashGeometry]]] = field(default_factory=dict)
    element_regions: Dict[str, List[Optional[QPainterPath]]] = field(default_factory=dict)
    flash_regions: Dict[frozenset[str], tuple[QRegion, int, int]] = field(default_factory=dict)

    def invalidate(self):
        """Invalidate entire cache - called on scroll/resize."""
        self.invalidate_elements()
        self.invalidate_clip_rects()

    def invalidate_elements(self) -> None:
        """Invalidate element geometry while preserving scroll-area discovery."""
        self.valid = False
        self.element_rects.clear()
        self.element_regions.clear()
        self.flash_regions.clear()

    def invalidate_clip_rects(self) -> None:
        """Invalidate scroll-area clip rectangles."""
        self.clip_rects_valid = False
        self.scroll_clip_rects.clear()

    def invalidate_key(self, key: str) -> None:
        """Invalidate cached geometry for one flash key."""
        self.valid = False
        self.element_rects.pop(key, None)
        self.element_regions.pop(key, None)
        self.flash_regions.clear()


@dataclass
class FlashElement:
    """Abstract representation of a flashable UI element.

    Provides a geometry callback that returns the element's rect in window coords.
    Works for ANY element type: groupboxes, tree items, list items, etc.
    """
    key: str  # Scoped ObjectState path that owns this visual element.
    get_rect_in_window: Callable[[QWidget], Optional[QRect]]
    get_child_rects: Optional[Callable[[QWidget], List[Tuple[QRect, bool]]]] = None  # For masking child widgets
    needs_scroll_clipping: bool = True  # Groupboxes need clipping, list/tree items don't (they handle it themselves)
    source_id: Optional[str] = None  # Unique identifier for deduplication (e.g., "groupbox:123", "list_item:scope_id")
    corner_radius: float = 0.0  # Rounded corners (0 = sharp, >0 = rounded)
    skip_overlay_paint: bool = False  # If True, overlay skips painting (element handles its own paint, e.g., list item delegate)
    hierarchical_key_prefix: bool = False  # If True, descendant ObjectState keys also repaint this delegate element.
    # Widget whose viewport needs updating when skip_overlay_paint=True.
    delegate_widget: Optional[QWidget] = None
    get_model_index: Optional[Callable[[], Any]] = None  # Returns QModelIndex for targeted item updates (avoids full viewport repaint)
    layout_watch_widgets: Tuple[QWidget, ...] = field(default_factory=tuple)
    scroll_clip_widget: Optional[QWidget] = None  # Visual owner whose ancestor viewports bound this element.


def _scroll_clip_rects_for_element(
    element: FlashElement,
    window: QWidget,
) -> List[QRect]:
    """Return only the viewport bounds that own an element's visual target."""
    from PyQt6.QtWidgets import QAbstractScrollArea

    clip_rects: List[QRect] = []
    widget = element.scroll_clip_widget
    while widget is not None and widget is not window:
        if isinstance(widget, QAbstractScrollArea):
            viewport = widget.viewport()
            if (
                viewport is not None
                and not sip.isdeleted(viewport)
                and viewport.isVisible()
            ):
                viewport_rect = viewport.rect()
                global_pos = viewport.mapToGlobal(viewport_rect.topLeft())
                window_pos = window.mapFromGlobal(global_pos)
                clip_rects.append(QRect(window_pos, viewport_rect.size()))
        widget = widget.parentWidget()
    return clip_rects


def _clip_rect_to_scroll_hierarchy(
    rect: QRect,
    clip_rects: List[QRect],
) -> Optional[QRect]:
    """Intersect a visual rect with every viewport in its owning hierarchy."""
    intersection = QRect(rect)
    for clip_rect in clip_rects:
        intersection = intersection.intersected(clip_rect)
        if not intersection.isValid():
            return None
    return intersection


@dataclass(frozen=True)
class OverlayFlashPaintRecord:
    """One deduplicated overlay paint operation for a visual flash source."""

    source_token: str
    key: str
    rect: QRect
    radius: float
    path: Optional[QPainterPath]
    color: Optional[QColor] = None


# Mask strategy identifiers
_MASK_STRATEGY_CHECKBOX_STYLE = "checkbox_style"
_MASK_STRATEGY_LABEL_SIZEHINT = "label_sizehint"
_MASK_STRATEGY_WIDGET_RECT = "widget_rect"
_MASK_STRATEGY_FIXED_SQUARE = "fixed_square"

# Mask strategy table (single source of truth)
_MASK_STRATEGY_BY_WIDGET: Dict[type, str] = {
    # Tight mask for checkmarks + label text
    QCheckBox: _MASK_STRATEGY_CHECKBOX_STYLE,
    # Tight mask for labels (avoid empty layout space)
    QLabel: _MASK_STRATEGY_LABEL_SIZEHINT,
}

# Leaf widget types used for groupbox child masking
LEAF_WIDGET_TYPES = (QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox,
                     QPushButton, QToolButton, QTextEdit, QPlainTextEdit,
                     QTreeWidget, QListWidget, QTableWidget, QLabel)

def _resolve_mask_strategy(widget: QWidget) -> str:
    """Resolve which masking strategy to use for a widget.

    Returns a strategy id string from _MASK_STRATEGY_BY_WIDGET,
    falling back to widget rect masking for unknown types.
    """
    for widget_type, strategy in _MASK_STRATEGY_BY_WIDGET.items():
        if isinstance(widget, widget_type):
            return strategy
    # HelpButton: fixed-size square mask
    from pyqt_reactive.widgets.shared.clickable_help_components import HelpButton
    if isinstance(widget, HelpButton):
        return _MASK_STRATEGY_FIXED_SQUARE
    return _MASK_STRATEGY_WIDGET_RECT


def get_child_mask_rect(widget: QWidget, window: QWidget) -> QRect:
    """Get mask rectangle for a groupbox child widget.

    This is the single source of truth for child masking geometry used by
    both STANDARD and INVERSE groupbox flashes. Checkboxes and labels are
    masked tightly; all other widgets use their full rect size.

    Args:
        widget: Widget to mask
        window: Reference window for coordinate transformation

    Returns:
        QRect with position and size for masking
    """
    from PyQt6.QtCore import QPoint

    widget_global = widget.mapToGlobal(QPoint(0, 0))
    widget_window = window.mapFromGlobal(widget_global)

    strategy = _resolve_mask_strategy(widget)

    # QCheckBox: use style subelement rects for indicator + (optional) label
    if strategy == _MASK_STRATEGY_CHECKBOX_STYLE:
        checkbox_widget = widget if isinstance(widget, QCheckBox) else None
        option = QStyleOptionButton()
        if checkbox_widget is not None:
            checkbox_widget.initStyleOption(option)
            option.rect = checkbox_widget.rect()
        else:
            option.rect = widget.rect()

        indicator_rect = widget.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, widget)
        contents_rect = widget.style().subElementRect(QStyle.SubElement.SE_CheckBoxContents, option, widget)
        checkbox_rect = indicator_rect
        if checkbox_widget is not None and checkbox_widget.text():
            checkbox_rect = checkbox_rect.united(contents_rect)

        result = QRect(widget_window.x() + checkbox_rect.x(),
                       widget_window.y() + checkbox_rect.y(),
                       checkbox_rect.width(),
                       checkbox_rect.height())
        logger.debug(f"[FLASH] get_child_mask_rect(QCheckBox): indicator={indicator_rect}, contents={contents_rect}, result={result}")
        return result

    # QLabel: use sizeHint to avoid masking empty layout space
    if strategy == _MASK_STRATEGY_LABEL_SIZEHINT:
        widget_size = widget.sizeHint()
        logger.debug(f"[FLASH] get_child_mask_rect(QLabel): using sizeHint={widget_size}")
        if widget_size.isEmpty():
            widget_size = widget.minimumSize()
            logger.debug(f"[FLASH] get_child_mask_rect(QLabel): fallback to minimumSize={widget_size}")
        if widget_size.isEmpty():
            widget_size = widget.rect().size()
            logger.debug(f"[FLASH] get_child_mask_rect(QLabel): fallback to rect().size()={widget_size}")

        widget_geom = widget.geometry()
        y_offset = (widget_geom.height() - widget_size.height()) // 2
        result = QRect(widget_window.x(), widget_window.y() + y_offset, widget_size.width(), widget_size.height())
        logger.debug(f"[FLASH] get_child_mask_rect(QLabel): result={result}")
        return result

    # HelpButton: use fixed square size if set
    if strategy == _MASK_STRATEGY_FIXED_SQUARE:
        square_size = widget.size()
        from pyqt_reactive.widgets.shared.clickable_help_components import HelpButton
        if isinstance(widget, HelpButton) and widget._square_size:
            square_size = QSize(widget._square_size, widget._square_size)
        widget_geom = widget.geometry()
        y_offset = (widget_geom.height() - square_size.height()) // 2
        result = QRect(widget_window.x(), widget_window.y() + y_offset, square_size.width(), square_size.height())
        logger.debug(f"[FLASH] get_child_mask_rect(HelpButton): result={result}")
        return result

    # Other widgets: use actual rect size to avoid partial masking
    widget_size = widget.rect().size()
    logger.debug(f"[FLASH] get_child_mask_rect({type(widget).__name__}): using rect().size()={widget_size}")

    widget_geom = widget.geometry()
    y_offset = (widget_geom.height() - widget_size.height()) // 2
    result = QRect(widget_window.x(), widget_window.y() + y_offset, widget_size.width(), widget_size.height())
    logger.debug(f"[FLASH] get_child_mask_rect({type(widget).__name__}): result={result}")
    return result


def resolve_mask_widgets(widget: Optional[QWidget], preferred_types: tuple) -> List[QWidget]:
    """Resolve visible child widgets to mask.

    If the given widget isn't a preferred type, attempts to find visible
    children of preferred types. Falls back to the original widget.
    """
    if widget is None:
        return []
    if sip.isdeleted(widget):
        return []
    if isinstance(widget, preferred_types):
        return [widget]
    matches = [
        child
        for child in widget.findChildren(QWidget)
        if not sip.isdeleted(child)
        and child.isVisible()
        and isinstance(child, preferred_types)
    ]
    if matches:
        return matches
    return [widget]


def _unique_live_widgets(widgets: Iterable[Optional[QWidget]]) -> Tuple[QWidget, ...]:
    """Return live widgets in first-seen order."""
    unique_widgets: list[QWidget] = []
    seen_widget_ids: set[int] = set()
    for widget in widgets:
        if widget is None or sip.isdeleted(widget):
            continue
        widget_id = id(widget)
        if widget_id in seen_widget_ids:
            continue
        seen_widget_ids.add(widget_id)
        unique_widgets.append(widget)
    return tuple(unique_widgets)


def needs_square_checkbox_mask(widget: QWidget) -> bool:
    """Return True when a checkbox should use square cutout.

    Textless checkboxes (no label) use square cutouts to avoid rounding the box.
    Checkboxes with labels are rounded like other widgets.
    """
    return isinstance(widget, QCheckBox) and not widget.text()


def _unmasked_groupbox_widgets(groupbox: QWidget) -> set[QWidget]:
    """Return widgets explicitly left readable during standard groupbox flashes."""
    if isinstance(groupbox, VisualUpdateMixin):
        return set(groupbox.flash_unmasked_widgets())
    return set()


def container_descendant_mask_watch_widgets(container: QWidget) -> Tuple[QWidget, ...]:
    """Return visible descendant widgets whose geometry defines standard masks."""
    unmasked_widgets = _unmasked_groupbox_widgets(container)
    mask_widgets: list[QWidget] = []
    if (
        isinstance(container, VisualUpdateMixin)
        and container.flash_masks_descendant_leaf_widgets()
    ):
        mask_widgets.extend(
            child
            for child in container.findChildren(QWidget)
            if child.isVisibleTo(container)
            and isinstance(child, LEAF_WIDGET_TYPES)
            and child not in unmasked_widgets
        )
        mask_widgets.extend(_get_function_pane_title_widgets(container))
    else:
        mask_widgets.extend(
            child
            for child in container.children()
            if isinstance(child, QWidget)
            and child.isVisibleTo(container)
            and child not in unmasked_widgets
        )
    return _unique_live_widgets(mask_widgets)


def container_descendant_mask_rects(container: QWidget, window: QWidget) -> List[Tuple[QRect, bool]]:
    """Return standard child/control masks for a container flash."""
    child_rects: List[Tuple[QRect, bool]] = []
    for child in container_descendant_mask_watch_widgets(container):
        if sip.isdeleted(child) or not child.isVisibleTo(container):
            continue
        child_rect = get_child_mask_rect(child, window)
        child_rects.append((child_rect, needs_square_checkbox_mask(child)))
    child_rects.extend(_get_groupbox_title_mask_rects(container, window))
    return child_rects


def _groupbox_mask_watch_widgets(
    groupbox: QWidget,
    leaf_widget: Optional[QWidget],
    label_widget: Optional[QWidget],
    *,
    inverse_masking: bool,
    use_full_rect: bool = False,
) -> Tuple[QWidget, ...]:
    """Return widgets whose geometry contributes to a groupbox flash path."""
    watch_widgets: list[QWidget | None] = [groupbox]

    if use_full_rect:
        return _unique_live_widgets(watch_widgets)

    if leaf_widget is not None or inverse_masking:
        watch_widgets.extend(resolve_mask_widgets(leaf_widget, LEAF_WIDGET_TYPES))
        watch_widgets.extend(resolve_mask_widgets(label_widget, (QLabel,)))
        watch_widgets.extend(_get_function_pane_title_widgets(groupbox))
        return _unique_live_widgets(watch_widgets)

    watch_widgets.extend(container_descendant_mask_watch_widgets(groupbox))

    return _unique_live_widgets(watch_widgets)


def groupbox_flash_source_id(
    key: str,
    groupbox: QWidget,
    *,
    leaf_widget: Optional[QWidget] = None,
    label_widget: Optional[QWidget] = None,
    inverse_masking: bool = False,
    use_full_rect: bool = False,
) -> str:
    """Return the visual identity for a groupbox flash element."""
    if use_full_rect:
        return f"groupbox_full:{id(groupbox)}"
    if leaf_widget is not None:
        return (
            f"leaf_flash:{id(groupbox)}:{id(leaf_widget)}:"
            f"{id(label_widget) if label_widget is not None else 'none'}"
        )
    if inverse_masking:
        return f"masked_container:{id(groupbox)}:{key}"
    return f"groupbox:{id(groupbox)}"


def widget_rect_flash_source_id(widget: QWidget) -> str:
    """Return the visual identity for a direct widget-rect flash element."""
    return f"widget_rect:{id(widget)}"


def table_cell_flash_source_id(target: "StructuralTableCellTarget") -> str:
    """Return the visual identity for an item-backed table cell flash."""
    return (
        f"table_cell:{id(target.table)}:"
        f"{target.row_index}:{target.column_index}"
    )


def _container_rect_in_window(
    container: QWidget,
    window: QWidget,
    *,
    use_full_rect: bool = False,
) -> Optional[QRect]:
    """Return a groupbox/container flash rect in window coordinates."""
    try:
        if not container.isVisible() or not container.isVisibleTo(window):
            return None

        from PyQt6.QtCore import QPoint

        if use_full_rect:
            global_pos = container.mapToGlobal(QPoint(0, 0))
            window_pos = window.mapFromGlobal(global_pos)
            size = container.size()
            return QRect(window_pos.x(), window_pos.y(), size.width(), size.height())

        margin_top = 0
        stylesheet = container.styleSheet()
        if stylesheet:
            match = re.search(r'margin-top\s*:\s*(\d+)', stylesheet)
            if match:
                margin_top = int(match.group(1))
        else:
            parent = container.parentWidget()
            while parent:
                stylesheet = parent.styleSheet()
                if stylesheet and 'QGroupBox' in stylesheet:
                    match = re.search(r'margin-top\s*:\s*(\d+)', stylesheet)
                    if match:
                        margin_top = int(match.group(1))
                    break
                parent = parent.parentWidget()

        global_pos = container.mapToGlobal(QPoint(0, margin_top))
        window_pos = window.mapFromGlobal(global_pos)
        size = container.size()
        adjusted_height = size.height() - margin_top
        return QRect(window_pos.x(), window_pos.y(), size.width(), adjusted_height)
    except RuntimeError:
        return None


def _get_function_pane_title_widgets(groupbox: QWidget) -> List[QWidget]:
    """Collect title-row widgets declared by a flash-aware ancestor.

    Returns visible widgets that should be masked tightly (buttons, labels, checkboxes).
    """
    widget: QWidget | None = groupbox
    while widget is not None:
        if isinstance(widget, VisualUpdateMixin):
            widgets = list(widget.flash_title_mask_widgets())
            if widgets:
                break
        widget = widget.parentWidget()
    else:
        return []

    # Deduplicate while preserving order
    seen = set()
    unique_widgets = []
    for widget in widgets:
        if id(widget) in seen:
            continue
        seen.add(id(widget))
        unique_widgets.append(widget)
    return unique_widgets


def _get_groupbox_title_mask_rects(groupbox: QWidget, window: QWidget) -> List[Tuple[QRect, bool]]:
    """Return mask rects for visible QGroupBox title text painted by Qt styles."""
    from PyQt6.QtWidgets import QGroupBox
    from PyQt6.QtCore import QPoint

    rects: List[Tuple[QRect, bool]] = []
    for titled_group in groupbox.findChildren(QGroupBox):
        title = titled_group.title()
        if not title or not titled_group.isVisible() or not titled_group.isVisibleTo(window):
            continue

        metrics = titled_group.fontMetrics()
        group_window_pos = window.mapFromGlobal(titled_group.mapToGlobal(QPoint(0, 0)))
        stylesheet = titled_group.styleSheet()
        left_padding = 6
        extra_width = 8
        if stylesheet:
            import re
            left_match = re.search(r"left\s*:\s*(\d+)", stylesheet)
            if left_match:
                left_padding = int(left_match.group(1))
            padding_match = re.search(r"padding\s*:\s*0\s+(\d+)", stylesheet)
            if padding_match:
                extra_width = int(padding_match.group(1)) * 2

        rects.append((
            QRect(
                group_window_pos.x() + left_padding,
                group_window_pos.y(),
                metrics.horizontalAdvance(title) + extra_width,
                metrics.height() + 4,
            ),
            False,
        ))
    return rects


def create_groupbox_element(
    key: str,
    groupbox: 'QGroupBox',
    leaf_widget: Optional[QWidget] = None,
    label_widget: Optional[QWidget] = None,
    use_full_rect: bool = False,
    inverse_masking: bool = False,
    extra_mask_rects: Optional[Callable[[QWidget], Iterable[Tuple[QRect, bool]]]] = None,
    extra_layout_watch_widgets: Iterable[QWidget] = (),
) -> FlashElement:
    """Create a FlashElement for a QGroupBox with configurable masking.

    Maps groupbox position to WINDOW coordinates (not scroll content coordinates).
    This accounts for scroll position so rects are in visible window space.

    Masking modes (determined by leaf_widget parameter):
    - leaf_widget=None and inverse_masking=False: STANDARD mode - mask ALL children, flash only frame/background
    - leaf_widget=widget or inverse_masking=True: INVERSE mode - mask ONLY title + leaf_widget/extra masks + label_widget, flash frame + all siblings

    Args:
        key: Flash key
        groupbox: The QGroupBox to flash
        leaf_widget: If provided, use inverse masking (flash siblings, mask this widget)
        label_widget: Optional label widget to mask (used with leaf_widget in INVERSE mode)
        inverse_masking: Use inverse masking even when the changed target is not a widget.
        extra_mask_rects: Window-relative mask rectangles for structural targets such as table cells.
        extra_layout_watch_widgets: Additional widgets whose geometry affects structural masks.
    """
    # Track groupbox size to detect resize and invalidate child cache
    _last_groupbox_size: Optional[tuple] = None
    # Cache child widgets list (doesn't change unless groupbox resizes)
    _cached_child_widgets: Optional[List[QWidget]] = None

    def get_rect(window: QWidget) -> Optional[QRect]:
        return _container_rect_in_window(
            groupbox,
            window,
            use_full_rect=use_full_rect,
        )

    def get_child_rects(window: QWidget) -> List[Tuple[QRect, bool]]:
        """Get widgets to exclude from flash (mask out).

        Two modes based on leaf_widget parameter:
        - STANDARD (leaf_widget=None): Mask ALL children, flash only frame/background
        - INVERSE (leaf_widget set): Mask ONLY title + leaf_widget, flash frame + all siblings

        INVALIDATION: Re-scans children when groupbox size changes (resize event).
        PERFORMANCE: Caches child widget list (expensive findChildren).
        Computes fresh window-relative rects on each call (cheap coordinate transform).
        """
        nonlocal _last_groupbox_size, _cached_child_widgets

        logger.debug(f"[FLASH] get_child_rects START: leaf_widget={type(leaf_widget).__name__ if leaf_widget else None}, label_widget={type(label_widget).__name__ if label_widget else None}, groupbox={type(groupbox).__name__}")
        
        # If the groupbox isn't visible to this window (e.g., tab not selected), skip masking
        if not groupbox.isVisible() or not groupbox.isVisibleTo(window):
            return []

        from PyQt6.QtCore import QPoint

        # INVERSE MODE: Mask title row + leaf_widget + label_widget only
        # All other widgets get flashed
        if leaf_widget is not None or inverse_masking:
            logger.debug(f"[FLASH] INVERSE MODE: Masking title + leaf_widget + label_widget only")
            exclusions: List[Tuple[QRect, bool]] = []
            try:
                if leaf_widget is not None and not leaf_widget.isVisible():
                    return []

                # Get groupbox top for title row detection
                from PyQt6.QtCore import QPoint
                groupbox_global = groupbox.mapToGlobal(QPoint(0, 0))
                title_height = groupbox.fontMetrics().height() + 20  # Title row height
                title_y_max = groupbox_global.y() + title_height

                mask_leaf_widgets = resolve_mask_widgets(leaf_widget, LEAF_WIDGET_TYPES)
                mask_label_widgets = resolve_mask_widgets(label_widget, (QLabel,))

                # Add leaf_widget to exclusions using precise masking
                for mask_leaf_widget in mask_leaf_widgets:
                    try:
                        leaf_rect = get_child_mask_rect(mask_leaf_widget, window)
                        logger.debug(f"[FLASH INVERSE] Added leaf_widget exclusion: {leaf_rect}")
                        exclusions.append((leaf_rect, needs_square_checkbox_mask(mask_leaf_widget)))
                    except Exception as e:
                        logger.warning(f"[FLASH INVERSE] Failed to mask leaf_widget: {e}")

                # Add label_widget to exclusions using precise masking
                for mask_label_widget in mask_label_widgets:
                    if not mask_label_widget.isVisible():
                        continue
                    try:
                        label_rect = get_child_mask_rect(mask_label_widget, window)
                        logger.debug(f"[FLASH INVERSE] Added label_widget exclusion: {label_rect}")
                        exclusions.append((label_rect, False))
                    except Exception as e:
                        logger.warning(f"[FLASH INVERSE] Failed to mask label_widget: {e}")

                if extra_mask_rects is not None:
                    for extra_rect, needs_square_cutout in extra_mask_rects(window):
                        if extra_rect.isValid() and not extra_rect.isNull():
                            exclusions.append((extra_rect, needs_square_cutout))

                # Mask title row widgets only for real groupboxes (avoid masking first row in plain containers)
                from PyQt6.QtWidgets import QGroupBox
                if isinstance(groupbox, QGroupBox) and groupbox.title():
                    for child in groupbox.findChildren(QWidget):
                        try:
                            if not child.isVisible() or not isinstance(child, LEAF_WIDGET_TYPES):
                                continue

                            # Skip leaf_widget and label_widget (already added above)
                            if child is leaf_widget or (label_widget is not None and child is label_widget):
                                continue

                            child_global = child.mapToGlobal(QPoint(0, 0))
                            child_y = child_global.y()

                            # Only mask title row widgets - not widgets in leaf_widget's row
                            if child_y < title_y_max:
                                child_rect = get_child_mask_rect(child, window)
                                logger.debug(f"[FLASH INVERSE] Added title row exclusion: {child_rect}")
                                exclusions.append((child_rect, needs_square_checkbox_mask(child)))
                        except Exception as e:
                            logger.warning(f"[FLASH INVERSE] Failed to mask title child {type(child).__name__}: {e}")
                            pass

                # Function panes: mask title row widgets tightly
                for title_widget in _get_function_pane_title_widgets(groupbox):
                    try:
                        title_rect = get_child_mask_rect(title_widget, window)
                        exclusions.append((title_rect, needs_square_checkbox_mask(title_widget)))
                    except Exception as e:
                        logger.warning(f"[FLASH INVERSE] Failed to mask function pane title widget: {e}")

                exclusions.extend(_get_groupbox_title_mask_rects(groupbox, window))

                logger.debug(f"[FLASH INVERSE] Total exclusions: {len(exclusions)}")
            except Exception as e:
                logger.error(f"[FLASH INVERSE] Outer exception: {e}", exc_info=True)
                return []
            logger.debug(f"[FLASH] INVERSE MODE: Returning {len(exclusions)} exclusions")
            return exclusions

        # STANDARD MODE: Mask all children
        logger.debug(f"[FLASH] STANDARD MODE: Masking all children")
        child_rects: List[Tuple[QRect, bool]] = []
        groupbox_global = groupbox.mapToGlobal(QPoint(0, 0))
        groupbox_window = window.mapFromGlobal(groupbox_global)

        # Invalidate child cache if groupbox size changed
        current_size = (groupbox.width(), groupbox.height())
        if _last_groupbox_size != current_size:
            _cached_child_widgets = None
            _last_groupbox_size = current_size

        # Cache child widgets list (expensive findChildren) on first call or after invalidation
        if _cached_child_widgets is None:
            _cached_child_widgets = list(
                container_descendant_mask_watch_widgets(groupbox)
            )

        # Compute fresh window-relative rects using standard groupbox child geometry
        for child in _cached_child_widgets:
            if sip.isdeleted(child) or not child.isVisibleTo(groupbox):
                continue
            child_rect = get_child_mask_rect(child, window)
            child_rects.append((child_rect, needs_square_checkbox_mask(child)))

        child_rects.extend(_get_groupbox_title_mask_rects(groupbox, window))

        # DEBUG: Log groupbox position and first 2 child positions
        if child_rects:
            first_children = [f"({r.x()},{r.y()})" for r, _ in child_rects[:2]]
            logger.debug(f"[FLASH] GET_CHILD_RECTS groupbox_id={id(groupbox)} groupbox_window_pos=({groupbox_window.x()},{groupbox_window.y()}) first_children={first_children} total={len(child_rects)}")
        logger.debug(f"[FLASH] STANDARD MODE: Returning {len(child_rects)} exclusions")
        return child_rects

    # Extract corner radius from groupbox stylesheet (cached)
    radius = get_widget_corner_radius(groupbox)
    if radius == 0:
        radius = default_container_corner_radius_px()

    return FlashElement(
        key=key,
        get_rect_in_window=get_rect,
        get_child_rects=None if use_full_rect else get_child_rects,
        source_id=groupbox_flash_source_id(
            key,
            groupbox,
            leaf_widget=leaf_widget,
            label_widget=label_widget,
            inverse_masking=inverse_masking,
            use_full_rect=use_full_rect,
        ),
        corner_radius=radius,
        layout_watch_widgets=_unique_live_widgets(
            (
                *_groupbox_mask_watch_widgets(
                    groupbox,
                    leaf_widget,
                    label_widget,
                    inverse_masking=inverse_masking,
                    use_full_rect=use_full_rect,
                ),
                *extra_layout_watch_widgets,
            )
        ),
        scroll_clip_widget=groupbox,
    )


def create_structural_masked_container_element(
    key: str,
    container: QWidget,
    mask_rects: Callable[[QWidget], Iterable[Tuple[QRect, bool]]],
    *,
    layout_watch_widgets: Iterable[QWidget] = (),
) -> FlashElement:
    """Create a FlashElement whose masks are fully supplied by a structural target."""

    def get_rect(window: QWidget) -> Optional[QRect]:
        return _container_rect_in_window(container, window)

    def get_child_rects(window: QWidget) -> List[Tuple[QRect, bool]]:
        if not container.isVisible() or not container.isVisibleTo(window):
            return []
        return [
            (mask_rect, needs_square_cutout)
            for mask_rect, needs_square_cutout in mask_rects(window)
            if mask_rect.isValid() and not mask_rect.isNull()
        ]

    radius = get_widget_corner_radius(container)
    if radius == 0:
        radius = default_container_corner_radius_px()

    return FlashElement(
        key=key,
        get_rect_in_window=get_rect,
        get_child_rects=get_child_rects,
        source_id=groupbox_flash_source_id(
            key,
            container,
            inverse_masking=True,
        ),
        corner_radius=radius,
        layout_watch_widgets=_unique_live_widgets((container, *layout_watch_widgets)),
        scroll_clip_widget=container,
    )


def create_widget_rect_element(key: str, widget: QWidget) -> FlashElement:
    """Create a FlashElement that paints a widget's full visible rectangle.

    This is for inline child widgets whose own contents are the thing being
    highlighted. Unlike groupbox flashes, it does not subtract child widgets from
    the paint region.
    """

    def get_rect(window: QWidget) -> Optional[QRect]:
        try:
            if not widget.isVisible() or not widget.isVisibleTo(window):
                return None

            from PyQt6.QtCore import QPoint

            global_pos = widget.mapToGlobal(QPoint(0, 0))
            window_pos = window.mapFromGlobal(global_pos)
            size = widget.size()
            return QRect(window_pos.x(), window_pos.y(), size.width(), size.height())
        except RuntimeError:
            return None

    radius = get_widget_corner_radius(widget)
    return FlashElement(
        key=key,
        get_rect_in_window=get_rect,
        get_child_rects=None,
        source_id=widget_rect_flash_source_id(widget),
        corner_radius=radius,
        layout_watch_widgets=(widget,),
        scroll_clip_widget=widget,
    )


def create_table_cell_element(key: str, target: "StructuralTableCellTarget") -> FlashElement:
    """Create a FlashElement for an item-backed table cell."""

    def get_rect(window: QWidget) -> Optional[QRect]:
        try:
            table = target.table
            if not table.isVisible() or not table.isVisibleTo(window):
                return None
            model_index = table.model().index(target.row_index, target.column_index)
            if not model_index.isValid():
                return None
            cell_rect = table.visualRect(model_index)
            if cell_rect.isNull():
                return None
            global_pos = table.viewport().mapToGlobal(cell_rect.topLeft())
            window_pos = window.mapFromGlobal(global_pos)
            return QRect(
                window_pos.x(),
                window_pos.y(),
                cell_rect.width(),
                cell_rect.height(),
            )
        except RuntimeError:
            return None

    return FlashElement(
        key=key,
        get_rect_in_window=get_rect,
        get_child_rects=None,
        source_id=table_cell_flash_source_id(target),
        layout_watch_widgets=(target.table, target.table.viewport()),
        scroll_clip_widget=target.table,
    )


def create_tree_item_element(key: str, tree: 'QTreeWidget', get_index: Callable[[], Any]) -> FlashElement:
    """Create a FlashElement for a tree item.

    Args:
        key: Flash key
        tree: The QTreeWidget
        get_index: Callback that returns the current QModelIndex (handles item recreation)

    Note: Uses skip_overlay_paint=True because TreeItemFlashDelegate handles
    drawing flash BEHIND text (same pattern as list items).
    """
    def get_rect(window: QWidget) -> Optional[QRect]:
        try:
            index = get_index()
            if index is None or not index.isValid():
                return None

            # Skip if tree or its viewport isn't visible in this window (hidden tab)
            if not tree.isVisible() or not tree.isVisibleTo(window):
                return None

            visual_rect = tree.visualRect(index)
            if not visual_rect.isValid():
                return None
            viewport = tree.viewport()
            if viewport is None:
                return None
            global_pos = viewport.mapToGlobal(visual_rect.topLeft())
            window_pos = window.mapFromGlobal(global_pos)
            return QRect(window_pos, visual_rect.size())
        except RuntimeError:
            return None
    return FlashElement(
        key=key,
        get_rect_in_window=get_rect,
        needs_scroll_clipping=False,
        source_id=f"tree:{id(tree)}:{key}",  # Include key to distinguish different items in same tree
        skip_overlay_paint=True,  # Delegate handles painting flash behind text
        hierarchical_key_prefix=True,
        delegate_widget=tree,  # Tree viewport needs updating during animation
        get_model_index=get_index,  # For targeted item updates (avoids full viewport repaint)
        layout_watch_widgets=(tree,),
    )


def create_list_item_element(key: str, list_widget: 'QListWidget', get_row: Callable[[], int]) -> FlashElement:
    """Create a FlashElement for a list item.

    Args:
        key: Flash key
        list_widget: The QListWidget
        get_row: Callback that returns the current row index (handles item recreation)

    The flash rect is inset from the item rect by the border width so the flash
    appears behind the text, not behind the borders.
    """
    # Try to get SCOPE_SCHEME_ROLE from the list item delegate module if available
    # This is an OpenHCS-specific extension for scope-based coloring
    try:
        from pyqt_reactive.widgets.shared.list_item_delegate import SCOPE_SCHEME_ROLE
    except ImportError:
        SCOPE_SCHEME_ROLE = None  # type: ignore

    def get_rect(window: QWidget) -> Optional[QRect]:
        try:
            row = get_row()
            item = list_widget.item(row)
            if item is None:
                return None

            # Skip if list or its viewport isn't visible in this window (hidden tab)
            if not list_widget.isVisible() or not list_widget.isVisibleTo(window):
                return None

            visual_rect = list_widget.visualItemRect(item)
            if not visual_rect.isValid():
                return None
            viewport = list_widget.viewport()
            if viewport is None:
                return None

            # Calculate border inset from scheme (flash behind text, not behind borders)
            border_inset = 0
            if SCOPE_SCHEME_ROLE is not None:
                scheme = item.data(SCOPE_SCHEME_ROLE)
                if scheme is not None:
                    layers = getattr(scheme, "step_border_layers", None)
                    if layers:
                        border_inset = sum(layer[0] for layer in layers)

            # Inset the rect by border width
            inset_rect = visual_rect.adjusted(border_inset, border_inset, -border_inset, -border_inset)

            global_pos = viewport.mapToGlobal(inset_rect.topLeft())
            window_pos = window.mapFromGlobal(global_pos)
            return QRect(window_pos, inset_rect.size())
        except RuntimeError:
            return None
    def get_model_index():
        """Get QModelIndex for targeted item update (avoids full viewport repaint)."""
        row = get_row()
        if row < 0:
            return None
        item = list_widget.item(row)
        # Use indexFromItem - O(1) vs model().index() overhead
        return list_widget.indexFromItem(item) if item else None

    return FlashElement(
        key=key,
        get_rect_in_window=get_rect,
        needs_scroll_clipping=False,
        source_id=f"list:{id(list_widget)}:{key}",  # Include key to distinguish different items in same list
        skip_overlay_paint=True,  # Delegate handles painting flash behind text
        hierarchical_key_prefix=True,
        delegate_widget=list_widget,  # List viewport needs updating during animation
        get_model_index=get_model_index,  # For targeted item updates (avoids full viewport repaint)
        layout_watch_widgets=(list_widget,),
    )


# ==================== WINDOW-LEVEL FLASH OVERLAY ====================
# ONE overlay per top-level window - renders ALL flash effects in ONE paintEvent

class WindowFlashOverlay(QWidget):
    """Transparent overlay that renders ALL flash effects for an entire window.

    TRUE GAME ENGINE ARCHITECTURE:
    - ONE instance per top-level window (QMainWindow/QDialog)
    - Renders ALL element types (groupboxes, tree items, list items) in ONE paintEvent
    - Elements register via FlashElement with geometry callbacks
    - Scales O(1) per window regardless of element count or type

    VIEWPORT CULLING: Elements outside visible scroll areas return None from
    their geometry callback and are skipped.
    """
    # Class-level registry: window_id -> overlay (weak refs for cleanup)
    _overlays: Dict[int, 'WindowFlashOverlay'] = {}

    @classmethod
    def get_for_window(cls, widget: QWidget) -> Optional['WindowFlashOverlay']:
        """Get or create the overlay for a top-level window (factory method).

        Automatically chooses between OpenGL and QPainter based on config and availability.

        Returns None if:
        - Widget is not yet in a proper window hierarchy
        - Widget has been deleted (RuntimeError from Qt C++ layer)
        """
        try:
            # Find the actual top-level window
            # This will raise RuntimeError if widget was deleted
            top_window = widget.window()

            # Only create overlays for REAL top-level windows, not widgets that
            # return themselves because they haven't been parented yet
            if not isinstance(top_window, (QMainWindow, QDialog)):
                return None

            window_id = id(top_window)
            overlay = cls._overlays.get(window_id)
            if overlay is not None:
                if cls._overlay_belongs_to_window(overlay, top_window):
                    return overlay
                cls._overlays.pop(window_id)
                flash_trace(
                    "overlay.replace_stale",
                    window=window_id,
                    overlay=id(overlay),
                )
                cls._discard_overlay(overlay)

            if window_id not in cls._overlays:
                # Factory: Choose OpenGL or QPainter overlay
                config = get_flash_config()

                if config.use_opengl:
                    # Try OpenGL first
                    try:
                        from .flash_overlay_opengl import WindowFlashOverlayGL, can_use_opengl
                        if can_use_opengl():
                            overlay = WindowFlashOverlayGL(top_window)
                            cls._overlays[window_id] = overlay
                            flash_trace(
                                "overlay.create_gl",
                                window=window_id,
                                overlay=id(overlay),
                            )
                            logger.info(f"[FLASH] Created OpenGL overlay for window {window_id} (GPU-accelerated)")
                            return cls._overlays[window_id]
                        else:
                            logger.warning("[FLASH] OpenGL 3.3+ not available, falling back to QPainter")
                    except Exception as e:
                        logger.warning(f"[FLASH] OpenGL overlay creation failed: {e}, falling back to QPainter")

                # Fallback to QPainter
                overlay = cls(top_window)
                cls._overlays[window_id] = overlay
                flash_trace(
                    "overlay.create_qpainter",
                    window=window_id,
                    overlay=id(overlay),
                    total=len(cls._overlays),
                )
                logger.debug(f"🧹 FLASH_LEAK_DEBUG: Created QPainter overlay for window {window_id}, "
                           f"total overlays: {len(cls._overlays)}")

            return cls._overlays[window_id]
        except RuntimeError:
            # Widget was deleted - return None gracefully
            return None

    @staticmethod
    def _overlay_belongs_to_window(
        overlay: 'WindowFlashOverlay',
        window: QWidget,
    ) -> bool:
        """Return whether a cached overlay is still attached to this Qt window."""
        try:
            return (
                not sip.isdeleted(overlay)
                and not sip.isdeleted(overlay._window)
                and overlay._window is window
            )
        except RuntimeError:
            return False

    @staticmethod
    def _discard_overlay(overlay: 'WindowFlashOverlay') -> None:
        """Clear and delete a stale overlay without consulting global registries."""
        try:
            if sip.isdeleted(overlay):
                return
            for source in overlay._event_filter_sources.values():
                if not sip.isdeleted(source):
                    source.removeEventFilter(overlay)
            overlay._event_filter_sources.clear()
            overlay._elements.clear()
            overlay._hierarchical_delegate_keys.clear()
            overlay.deleteLater()
        except RuntimeError:
            return

    @classmethod
    def cleanup_window(cls, window: QWidget) -> None:
        """Remove overlay for a window (call when window closes)."""
        try:
            window_id = id(window.window())
        except RuntimeError:
            return
        overlays_before = len(cls._overlays)
        overlay = cls._overlays.pop(window_id, None)
        overlays_after = len(cls._overlays)
        if overlay:
            # CRITICAL: Clear all registered elements BEFORE deleteLater()
            # Otherwise overlay might paint dead elements during async deletion
            elements_count = sum(len(v) for v in overlay._elements.values())
            flash_trace(
                "overlay.cleanup",
                window=window_id,
                overlay=id(overlay),
                elements=elements_count,
                before=overlays_before,
                after=overlays_after,
            )
            cls._discard_overlay(overlay)
            logger.debug(f"🧹 FLASH_LEAK_DEBUG: Cleaned up WindowFlashOverlay for window {window_id}, "
                       f"cleared {elements_count} elements, total overlays: {overlays_before} -> {overlays_after}")

    def __init__(self, window: QWidget):
        super().__init__(window)
        self._window = window
        self._elements: Dict[str, List[FlashElement]] = {}  # scoped ObjectState path -> elements
        self._hierarchical_delegate_keys: Set[str] = set()
        self._event_filter_sources: Dict[int, QObject] = {}
        self._element_widget_keys: Dict[int, Set[str]] = {}
        self._element_widget_signatures: Dict[int, Tuple[int, int, int, int, bool]] = {}
        self._scroll_areas: List[Any] = []
        self._scroll_areas_dirty = True
        self._needs_raise = True

        # FIX 3: Unified geometry cache with single invalidation point
        self._cache = OverlayGeometryCache()
        self._last_flash_update_region = QRegion()
        self._last_flash_mask_region = QRegion()

        # Make overlay transparent and pass mouse events through
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")

        # CRITICAL: Disable Qt's paint optimizations that clip to dirty regions
        # When another window occludes this window and then moves away, Qt only
        # sends paintEvents for the newly exposed "dirty" region. This causes
        # flashes to only appear in the occluded area. By setting WA_OpaquePaintEvent
        # to False, we tell Qt to always repaint the entire widget.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

        # Cover entire window
        self.setGeometry(window.rect())
        # Registered overlays are render surfaces, not permanent visible chrome.
        # Showing every transparent overlay as soon as a field registers makes
        # ordinary window repaint/compositing scale with the number of open
        # editors. The coordinator arms the overlay only while it has visible
        # flash work.
        self.hide()

        # Install event filter on scroll areas to catch scroll events
        self._install_scroll_event_filters()

    def register_element(self, element: FlashElement) -> None:
        """Register a flashable element. Multiple elements can share the same key.

        CRITICAL: Deduplicate based on (key, source_id) to prevent duplicate registrations
        while allowing multiple element types (tree item + groupbox) for the same key.
        """
        if element.key not in self._elements:
            self._elements[element.key] = []

        # Check if element with same source_id already exists
        if element.source_id is not None:
            for i, existing in enumerate(self._elements[element.key]):
                if existing.source_id == element.source_id:
                    if (
                        existing.skip_overlay_paint == element.skip_overlay_paint
                        and existing.hierarchical_key_prefix == element.hierarchical_key_prefix
                        and existing.delegate_widget is element.delegate_widget
                        and existing.get_model_index is element.get_model_index
                    ):
                        return
                    # Replace existing element with same source
                    self._elements[element.key][i] = element
                    self._invalidate_geometry_cache_for_key(element.key)
                    self._sync_hierarchical_delegate_key(element.key)
                    self._install_widget_event_filter(element)
                    flash_trace(
                        "overlay.register_replace",
                        window=id(self._window),
                        overlay=id(self),
                        key=element.key,
                        source=element.source_id,
                        keys=len(self._elements),
                    )
                    logger.debug(f"[FLASH] Replaced element: {element.key}, source_id={element.source_id}")
                    return

        # New element - append
        self._elements[element.key].append(element)
        self._needs_raise = True
        self._invalidate_geometry_cache_for_key(element.key)
        self._sync_hierarchical_delegate_key(element.key)
        total = sum(len(v) for v in self._elements.values())
        flash_trace(
            "overlay.register",
            window=id(self._window),
            overlay=id(self),
            key=element.key,
            source=element.source_id,
            keys=len(self._elements),
            elements=total,
        )
        logger.debug(f"[FLASH] Registered element: {element.key}, source_id={element.source_id}, total={total}")

        # Install event filter on the element's widget to catch resize/move events
        self._install_widget_event_filter(element)

    def has_element_source(self, key: str, source_id: str | None) -> bool:
        """Return whether this overlay already has a visual source for a key."""
        if source_id is None:
            return False
        return any(
            element.source_id == source_id
            for element in self._elements.get(key, ())
        )

    def unregister_element(self, key: str) -> None:
        """Unregister all elements for a key."""
        self._elements.pop(key, None)
        self._hierarchical_delegate_keys.discard(key)
        self._invalidate_geometry_cache_for_key(key)

    def unregister_element_source(self, key: str, source_id: str | None) -> None:
        """Unregister one element source for a key."""
        if source_id is None:
            self.unregister_element(key)
            return
        elements = self._elements.get(key)
        if not elements:
            return
        remaining = [
            element
            for element in elements
            if element.source_id != source_id
        ]
        if remaining:
            self._elements[key] = remaining
            self._sync_hierarchical_delegate_key(key)
        else:
            self._elements.pop(key, None)
            self._hierarchical_delegate_keys.discard(key)
        self._invalidate_geometry_cache_for_key(key)

    def _sync_hierarchical_delegate_key(self, key: str) -> None:
        """Track keys whose delegate elements subscribe to descendant flashes."""
        elements = self._elements.get(key, ())
        if any(
            element.skip_overlay_paint and element.hierarchical_key_prefix
            for element in elements
        ):
            self._hierarchical_delegate_keys.add(key)
        else:
            self._hierarchical_delegate_keys.discard(key)

    def _install_scroll_event_filters(self):
        """Install event filters on ALL scroll areas (QScrollArea, QTreeWidget, QListWidget, etc.)."""
        # Install filter on the window itself to catch layout changes
        self._install_event_filter_on(self._window)
        self._refresh_scroll_area_event_filters()

    def _install_event_filter_on(self, source: QObject) -> None:
        """Install once and retain the exact QObject for synchronous teardown."""
        source_id = id(source)
        if source_id in self._event_filter_sources:
            return
        self._event_filter_sources[source_id] = source
        source.installEventFilter(self)

    def _refresh_scroll_area_event_filters(self) -> None:
        """Refresh cached scroll areas and install viewport event filters."""
        from PyQt6.QtWidgets import QAbstractScrollArea

        scroll_areas = [
            scroll_area
            for scroll_area in self._window.findChildren(QAbstractScrollArea)
            if not sip.isdeleted(scroll_area)
        ]
        self._scroll_areas = scroll_areas
        self._scroll_areas_dirty = False
        self._cache.invalidate_clip_rects()

        for scroll_area in scroll_areas:
            viewport = scroll_area.viewport()
            if viewport is None or sip.isdeleted(viewport):
                continue
            self._install_event_filter_on(viewport)

    def _install_widget_event_filter(self, element: FlashElement) -> None:
        """Install event filter on a flash element's widget to catch layout changes.

        This ensures cache invalidation when element widgets change actual
        geometry. Text, placeholder, and style churn should not rebuild flash
        geometry unless Qt also moves, resizes, hides, or shows the widget.
        """
        for widget in element.layout_watch_widgets:
            if widget is None or sip.isdeleted(widget):
                continue
            widget_id = id(widget)
            self._element_widget_keys.setdefault(widget_id, set()).add(element.key)
            if widget_id in self._element_widget_signatures:
                continue
            self._element_widget_signatures[widget_id] = self._geometry_signature(widget)
            self._install_event_filter_on(widget)
            logger.debug("[FLASH] Installed event filter on widget %s", widget_id)

    def _invalidate_geometry_cache_for_widget(self, widget: QWidget) -> None:
        """Invalidate cached geometry for keys owned by a watched widget."""
        for key in self._element_widget_keys.get(id(widget), ()):
            self._invalidate_geometry_cache_for_key(key)

    def _invalidate_geometry_cache_if_widget_signature_changed(self, widget: QWidget) -> None:
        """Invalidate watched keys only when a widget's geometry contribution changed."""
        widget_id = id(widget)
        if widget_id not in self._element_widget_keys:
            return
        current_signature = self._geometry_signature(widget)
        if self._element_widget_signatures.get(widget_id) == current_signature:
            return
        self._element_widget_signatures[widget_id] = current_signature
        self._invalidate_geometry_cache_for_widget(widget)

    @staticmethod
    def _geometry_signature(widget: QWidget) -> Tuple[int, int, int, int, bool]:
        """Return the geometry facts used by flash mask/rect calculation."""
        geometry = widget.geometry()
        return (
            geometry.x(),
            geometry.y(),
            geometry.width(),
            geometry.height(),
            widget.isVisible(),
        )

    def eventFilter(self, obj, event):
        """Catch scroll/resize/layout events to invalidate geometry cache."""
        from PyQt6.QtCore import QEvent
        event_type = event.type()

        if event_type in (QEvent.Type.Resize, QEvent.Type.Move):
            logger.debug(f"[FLASH] Event filter caught {event_type} on {obj.__class__.__name__}, invalidating cache")
            if obj is self._window:
                self._invalidate_geometry_cache(include_scroll_areas=True)
                if event_type == QEvent.Type.Resize:
                    self.setGeometry(self._window.rect())
            elif isinstance(obj, QWidget):
                self._invalidate_geometry_cache_if_widget_signature_changed(obj)
        elif event_type in (
            QEvent.Type.LayoutRequest,
            QEvent.Type.Show,
            QEvent.Type.Hide,
            QEvent.Type.FontChange,
            QEvent.Type.StyleChange,
            QEvent.Type.ContentsRectChange,
        ):
            if isinstance(obj, QWidget):
                self._invalidate_geometry_cache_if_widget_signature_changed(obj)
        elif event_type == QEvent.Type.Wheel:
            logger.debug(f"[FLASH] Event filter caught {event_type} on {obj.__class__.__name__}, invalidating cache")
            self._invalidate_geometry_cache()
        elif event_type in (QEvent.Type.ChildAdded, QEvent.Type.ChildRemoved):
            self._scroll_areas_dirty = True
            self._needs_raise = True
            self._cache.invalidate_clip_rects()

        return super().eventFilter(obj, event)

    def _invalidate_geometry_cache(self, *, include_scroll_areas: bool = False):
        """Invalidate ALL cached geometry - called on scroll/resize."""
        self._cache.invalidate_elements()
        if include_scroll_areas:
            self._cache.invalidate_clip_rects()

    def _invalidate_geometry_cache_for_key(self, key: str) -> None:
        """Invalidate cached geometry for one flash key."""
        self._cache.invalidate_key(key)

    def invalidate_cache(self):
        """Public method to invalidate geometry cache.

        Call this when programmatically scrolling (e.g., scroll_to_section via tree item click).
        """
        self._invalidate_geometry_cache()

    @classmethod
    def invalidate_cache_for_widget(cls, widget: QWidget) -> None:
        """Invalidate geometry cache for the overlay covering a widget's window.

        Convenience method for programmatic scroll/resize operations.
        """
        overlay = cls.get_for_window(widget)
        if overlay:
            overlay.invalidate_cache()

    def _rebuild_geometry_cache(
        self,
        clip_rects: List[QRect],
        keys: Set[str] | None = None,
    ) -> None:
        """Rebuild ALL cached geometry and QRegion objects.

        CARMACK: This is expensive, but only called on scroll/resize or new element registration.
        During smooth animation, we just use the cached data.
        """
        rebuild_keys = set(keys) if keys is not None else set(self._elements)
        debug_enabled = logger.isEnabledFor(logging.DEBUG)
        source_geometry: dict[
            str,
            tuple[
                Optional[FlashGeometry],
                Optional[QPainterPath],
            ],
        ] = {}
        for key in rebuild_keys:
            self._cache.invalidate_key(key)

        for key in rebuild_keys:
            elements = self._elements.get(key, ())
            rects = []
            regions = []

            for element in elements:
                # Skip elements that handle their own paint (e.g., list item delegates)
                if element.skip_overlay_paint:
                    rects.append(None)
                    regions.append(None)
                    continue

                source_token = self._paint_source_token(key, len(rects), element)
                cached_source_geometry = source_geometry.get(source_token)
                if cached_source_geometry is not None:
                    rect_tuple, path = cached_source_geometry
                    rects.append(rect_tuple)
                    regions.append(path)
                    continue

                # Compute element rect in window coords
                rect = element.get_rect_in_window(self._window)

                if rect is None or not rect.isValid():
                    rects.append(None)
                    regions.append(None)
                    source_geometry[source_token] = (None, None)
                    continue

                # Apply scroll area clipping if needed
                rect_to_draw = rect
                if element.needs_scroll_clipping:
                    owning_clip_rects = self._scroll_clip_rects_for_element(element)
                    clipped_rect = self._clip_to_scroll_areas(
                        rect,
                        owning_clip_rects,
                    )
                    if not owning_clip_rects:
                        clipped_rect = rect
                    if clipped_rect and clipped_rect.isValid():
                        rect_to_draw = clipped_rect
                    else:
                        # Element not visible in scroll area - append None tuple placeholder
                        rects.append((None, 0.0))
                        regions.append(None)
                        source_geometry[source_token] = ((None, 0.0), None)
                        continue

                # Get corner radius from element (0 for tree/list items, >0 for groupboxes)
                radius = element.corner_radius

                if element.get_child_rects:
                    child_rects = tuple(element.get_child_rects(self._window))
                    path = QPainterPath()
                    path.addRoundedRect(QRectF(rect_to_draw), radius, radius)
                    subtracted_count = 0
                    first_children = [] if debug_enabled else None
                    for i, (child_rect, child_is_checkbox) in enumerate(child_rects):
                        if child_rect.intersects(rect_to_draw):
                            subtracted_count += 1
                            child_path = QPainterPath()
                            if child_is_checkbox:
                                child_path.addRect(QRectF(child_rect))
                            else:
                                child_path.addRoundedRect(QRectF(child_rect), radius, radius)
                            path = path.subtracted(child_path)
                        if debug_enabled and first_children is not None and i < 3:
                            first_children.append(f"({child_rect.x()},{child_rect.y()} {child_rect.width()}x{child_rect.height()})")
                    if debug_enabled:
                        short_key = key.split('::')[-1] if '::' in key else key[-30:]
                        logger.debug(
                            "[FLASH] CACHE_BUILD key=%s groupbox_rect=(%d,%d) first_child_rects=%s subtracted=%d/%d",
                            short_key,
                            rect_to_draw.x(),
                            rect_to_draw.y(),
                            first_children,
                            subtracted_count,
                            len(child_rects),
                    )
                    rect_tuple = (rect_to_draw, radius)
                    rects.append(rect_tuple)  # Cache rect + radius tuple
                    regions.append(path)
                    source_geometry[source_token] = (rect_tuple, path)
                else:
                    # No child masking - just cache rect + radius
                    if debug_enabled:
                        logger.debug(
                            "[FLASH] _rebuild_geometry_cache: key=%s source=%s rect=%d,%d %dx%d NO child masking radius=%s",
                            key,
                            element.source_id,
                            rect_to_draw.x(),
                            rect_to_draw.y(),
                            rect_to_draw.width(),
                            rect_to_draw.height(),
                            radius,
                        )
                    rect_tuple = (rect_to_draw, radius)
                    rects.append(rect_tuple)  # Cache rect + radius tuple
                    regions.append(None)
                    source_geometry[source_token] = (rect_tuple, None)

            self._cache.element_rects[key] = rects
            self._cache.element_regions[key] = regions

        self._cache.valid = True
        logger.debug(
            "[FLASH] Rebuilt geometry cache for window %s: rebuilt=%d cached=%d",
            id(self._window),
            len(rebuild_keys),
            len(self._cache.element_rects),
        )

    def _ensure_geometry_cache_for_keys(self, keys: Set[str]) -> None:
        """Ensure cached geometry exists for the requested overlay-painted keys."""
        missing_cache_keys = {
            key
            for key in keys
            if key not in self._cache.element_rects
        }
        if not missing_cache_keys:
            return
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "[FLASH] CACHE MISS - Rebuilding %d active keys for window %s",
                len(missing_cache_keys),
                id(self._window),
            )
        self._rebuild_geometry_cache(
            self._get_scroll_area_clip_rects(),
            missing_cache_keys,
        )

    @staticmethod
    def _paint_source_token(key: str, index: int, element: FlashElement) -> str:
        """Return the visual-source token used to deduplicate overlay painting."""
        if element.source_id is not None:
            return f"source:{element.source_id}"
        return f"key:{key}:{index}"

    def _visible_paint_records(
        self,
        keys: Set[str],
        *,
        colors: Optional[Dict[str, QColor]] = None,
    ) -> tuple[tuple[OverlayFlashPaintRecord, ...], int]:
        """Return deduplicated visible paint records for active overlay keys."""
        visible_keys = self.get_visible_keys_for(keys)
        if not visible_keys:
            return (), 0

        records_by_source: dict[str, OverlayFlashPaintRecord] = {}
        for key in visible_keys:
            elements = self._elements.get(key, ())
            cached_rects = self._cache.element_rects.get(key, ())
            cached_regions = self._cache.element_regions.get(key, ())
            color = colors.get(key) if colors is not None else None
            for index, element in enumerate(elements):
                if element.skip_overlay_paint:
                    continue
                if index >= len(cached_rects):
                    continue
                rect_tuple = cached_rects[index]
                if rect_tuple is None:
                    continue
                rect, radius = rect_tuple
                if rect is None or not rect.isValid():
                    continue

                path = cached_regions[index] if index < len(cached_regions) else None
                source_token = self._paint_source_token(key, index, element)
                record = OverlayFlashPaintRecord(
                    source_token=source_token,
                    key=key,
                    rect=rect,
                    radius=radius,
                    path=path,
                    color=color,
                )
                existing = records_by_source.get(source_token)
                if existing is None:
                    records_by_source[source_token] = record
                    continue
                if color is None:
                    continue
                existing_alpha = existing.color.alpha() if existing.color is not None else -1
                if color.alpha() > existing_alpha:
                    records_by_source[source_token] = record
        return tuple(records_by_source.values()), len(visible_keys)

    def _flash_region_for_keys(
        self,
        keys: Set[str],
    ) -> tuple[QRegion, int, int, int, float, float, float]:
        """Return the currently visible flash paint region for overlay-painted keys."""
        overlay_keys = keys & self._elements.keys()
        if not overlay_keys:
            return QRegion(), 0, 0, 0, 0.0, 0.0, 0.0

        missing_count = sum(
            1
            for key in overlay_keys
            if key not in self._cache.element_rects
        )
        started = time.perf_counter()
        self._ensure_geometry_cache_for_keys(overlay_keys)
        ensure_ms = (time.perf_counter() - started) * 1000.0

        region_cache_key = frozenset(overlay_keys)
        cached_region = self._cache.flash_regions.get(region_cache_key)
        if cached_region is not None:
            region, visible_key_count, rect_count = cached_region
            return (
                QRegion(region),
                visible_key_count,
                rect_count,
                missing_count,
                ensure_ms,
                0.0,
                0.0,
            )

        started = time.perf_counter()
        paint_records, visible_key_count = self._visible_paint_records(overlay_keys)
        visible_ms = (time.perf_counter() - started) * 1000.0
        if not paint_records:
            empty_region = QRegion()
            self._cache.flash_regions[region_cache_key] = (empty_region, 0, 0)
            return empty_region, 0, 0, missing_count, ensure_ms, visible_ms, 0.0

        started = time.perf_counter()
        region = QRegion()
        rect_count = 0
        overlay_rect = self.rect()
        for record in paint_records:
            paint_rect = record.rect.adjusted(-2, -2, 2, 2).intersected(overlay_rect)
            if paint_rect.isEmpty():
                continue
            region = region.united(QRegion(paint_rect))
            rect_count += 1
        region_ms = (time.perf_counter() - started) * 1000.0
        self._cache.flash_regions[region_cache_key] = (
            QRegion(region),
            visible_key_count,
            rect_count,
        )
        return (
            region,
            visible_key_count,
            rect_count,
            missing_count,
            ensure_ms,
            visible_ms,
            region_ms,
        )

    def request_flash_update_for_keys(
        self,
        keys: Set[str],
        *,
        clear_after: bool = False,
    ) -> tuple[int, int]:
        """Queue a minimal repaint region for active flash keys.

        The overlay is window-sized for z-order simplicity, but repainting the
        whole overlay every frame makes inherited config flashes scale with
        window area. Flash elements already own cached geometry, so use that as
        the repaint authority.
        """
        started = time.perf_counter()
        (
            current_region,
            visible_key_count,
            rect_count,
            missing_count,
            ensure_ms,
            visible_ms,
            region_ms,
        ) = self._flash_region_for_keys(keys)
        region_total_ms = (time.perf_counter() - started) * 1000.0
        started = time.perf_counter()
        update_region = current_region.united(self._last_flash_update_region)
        self._last_flash_update_region = QRegion() if clear_after else current_region
        union_ms = (time.perf_counter() - started) * 1000.0
        if update_region.isEmpty():
            return visible_key_count, rect_count
        if update_region != self._last_flash_mask_region:
            self.setMask(update_region)
            self._last_flash_mask_region = QRegion(update_region)
        if not self.isVisible():
            self.show()
            self._needs_raise = True
        if self._needs_raise:
            self.raise_()
            self._needs_raise = False
        started = time.perf_counter()
        self.update(update_region)
        update_ms = (time.perf_counter() - started) * 1000.0
        elapsed_ms = region_total_ms + union_ms + update_ms
        if TimeTravelProfiler.enabled() and elapsed_ms >= 5.0:
            logging.getLogger(TimeTravelProfiler.logger_name).info(
                "TT_PHASE name=%s elapsed_ms=%.3f window=%r keys=%r visible_keys=%r rects=%r missing=%r ensure_ms=%.3f visible_ms=%.3f region_ms=%.3f union_ms=%.3f update_ms=%.3f",
                "pyqt.flash.request_update",
                elapsed_ms,
                id(self._window),
                len(keys),
                visible_key_count,
                rect_count,
                missing_count,
                ensure_ms,
                visible_ms,
                region_ms,
                union_ms,
                update_ms,
            )
        return visible_key_count, rect_count

    def resizeEvent(self, event) -> None:
        """Resize to cover entire window."""
        super().resizeEvent(event)
        if self._window:
            self.setGeometry(self._window.rect())
            self._needs_raise = True
            # Invalidate ALL geometry caches on resize
            self._invalidate_geometry_cache(include_scroll_areas=True)

    def is_element_in_viewport(self, key: str) -> bool:
        """Check if any element for this key is visible (for viewport culling)."""
        elements = self._elements.get(key)
        if not elements:
            return False
        # Return True if ANY element for this key is visible
        for element in elements:
            rect = element.get_rect_in_window(self._window)
            if rect and rect.isValid() and rect.intersects(self.rect()):
                return True
        return False

    def get_visible_keys(self) -> Set[str]:
        """Get set of keys for elements currently visible in viewport."""
        return {key for key in self._elements if self.is_element_in_viewport(key)}

    def get_visible_keys_for(self, keys: Set[str]) -> Set[str]:
        """Get visible keys from a specific subset (avoids scanning all elements).

        PERFORMANCE FIX: Use cached geometry instead of recalculating every frame.
        This eliminates expensive coordinate transformations during animation.
        """
        visible: Set[str] = set()

        # If cache is valid, use cached rects (FAST PATH - no coordinate transforms!)
        if self._cache.valid:
            for key in keys:
                cached_rects = self._cache.element_rects.get(key, [])
                # Check if ANY cached rect is visible
                for rect_tuple in cached_rects:
                    if rect_tuple is None:
                        continue
                    rect, _ = rect_tuple  # Unpack (rect, radius) tuple
                    if rect is not None and rect.isValid() and rect.intersects(self.rect()):
                        visible.add(key)
                        break  # One visible element is enough
        else:
            # Cache invalid - fallback to live calculation (SLOW PATH - only during cache rebuild)
            for key in keys:
                elements = self._elements.get(key)
                if not elements:
                    continue
                for element in elements:
                    try:
                        rect = element.get_rect_in_window(self._window)
                    except RuntimeError:
                        continue
                    if rect is not None and rect.isValid() and rect.intersects(self.rect()):
                        visible.add(key)
                        break  # One visible element is enough
        return visible

    def _get_scroll_area_clip_rects(self) -> List[QRect]:
        """Find all QScrollArea viewports in the window and return their rects in window coords.

        Flash rectangles will be clipped to these areas to avoid bleeding over headers/buttons.

        PERFORMANCE: Cached - findChildren() is expensive (tree traversal).
        Cache invalidated on resize.
        """
        if self._cache.clip_rects_valid:
            return self._cache.scroll_clip_rects

        if self._scroll_areas_dirty:
            self._refresh_scroll_area_event_filters()

        clip_rects = []
        for scroll_area in self._scroll_areas:
            if sip.isdeleted(scroll_area):
                self._scroll_areas_dirty = True
                continue
            viewport = scroll_area.viewport()
            if viewport is None or sip.isdeleted(viewport) or not viewport.isVisible():
                continue
            # Get viewport rect in window coordinates
            viewport_rect = viewport.rect()
            global_pos = viewport.mapToGlobal(viewport_rect.topLeft())
            window_pos = self._window.mapFromGlobal(global_pos)
            clip_rects.append(QRect(window_pos, viewport_rect.size()))

        self._cache.scroll_clip_rects = clip_rects
        self._cache.clip_rects_valid = True
        return clip_rects

    def _scroll_clip_rects_for_element(self, element: FlashElement) -> List[QRect]:
        """Return only the viewport bounds that own an element's visual target."""
        return _scroll_clip_rects_for_element(element, self._window)

    def _clip_to_scroll_areas(
        self,
        rect: QRect,
        clip_rects: List[QRect],
    ) -> Optional[QRect]:
        """Intersect a flash rect with every viewport in its owning hierarchy."""
        return _clip_rect_to_scroll_hierarchy(rect, clip_rects)

    def paintEvent(self, event) -> None:
        """GAME ENGINE: Render ALL flash effects in ONE paint call.

        CARMACK OPTIMIZATION: Cache ALL geometry and QRegion objects.
        Recompute ONLY on scroll/resize events.
        During smooth animation: ZERO coordinate transformations, ZERO QRegion operations.
        """
        coordinator = _GlobalFlashCoordinator.get()

        # FIX 1: Single unified color lookup (all keys are scoped)
        if not coordinator._computed_colors:
            return  # Nothing animating

        # Only consider keys that are both animating and registered in this overlay
        active_keys = {
            key: color
            for key, color in coordinator._computed_colors.items()
            if key in self._elements
        }
        if not active_keys:
            return  # Nothing to draw for this window

        # CRITICAL: If window has _scope_color_scheme, override flash colors to match
        # This ensures step editor flashes match the list item's visual position-based colors
        window_scheme = getattr(self._window, '_scope_color_scheme', None)
        if window_scheme:
            scheme_color = window_scheme.accent_qcolor()
            active_keys = {
                key: QColor(
                    scheme_color.red(),
                    scheme_color.green(),
                    scheme_color.blue(),
                    color.alpha(),
                )
                for key, color in active_keys.items()
            }

        active_key_set = set(active_keys)
        self._ensure_geometry_cache_for_keys(active_key_set)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("[FLASH] CACHE HIT - Using cached geometry for window %s", id(self._window))

        # Filter to only visual sources whose elements are currently visible in this
        # window, then collapse multiple active ObjectState keys that resolve to the
        # same source. A fanout update can legitimately activate several paths for
        # one groupbox/container; the overlay should paint that source once.
        paint_records, _visible_key_count = self._visible_paint_records(
            active_key_set,
            colors=active_keys,
        )
        if not paint_records:
            # No active target intersects the dirty region. The coordinator
            # includes the previous flash region in clear updates, so there is
            # no useful full-window transparent paint here.
            return

        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        drawn_count = 0

        debug_enabled = logger.isEnabledFor(logging.DEBUG)
        if debug_enabled:
            logger.debug("[FLASH] paintEvent START: %d sources to draw", len(paint_records))

        dirty_rect = event.region().boundingRect()
        for record in paint_records:
            rect = record.rect
            color = record.color
            if color is None:
                continue
            if not rect.isValid() or not rect.intersects(dirty_rect):
                if debug_enabled:
                    short_key = record.key.split('::')[-1] if '::' in record.key else record.key[-30:]
                    logger.debug(
                        "[FLASH] SKIPPED key=%s source=%s rect=%s (invalid or off-screen)",
                        short_key,
                        record.source_token,
                        rect,
                    )
                continue

            painter.save()
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            if record.path is not None:
                if debug_enabled:
                    short_key = record.key.split('::')[-1] if '::' in record.key else record.key[-30:]
                    br = record.path.boundingRect()
                    logger.debug(
                        "[FLASH] DRAWING WITH PATH key=%s source=%s fillRect=%d,%d %dx%d path.boundingRect=%.0f,%.0f %.0fx%.0f",
                        short_key,
                        record.source_token,
                        rect.x(),
                        rect.y(),
                        rect.width(),
                        rect.height(),
                        br.x(),
                        br.y(),
                        br.width(),
                        br.height(),
                    )
                painter.drawPath(record.path)
            elif record.radius > 0:
                painter.drawRoundedRect(QRectF(rect), record.radius, record.radius)
            else:
                painter.fillRect(rect, color)
            painter.restore()

            if debug_enabled:
                short_key = record.key.split('::')[-1] if '::' in record.key else record.key[-30:]
                logger.debug(
                    "[FLASH] DREW RECT key=%s source=%s rect=%d,%d %dx%d radius=%s path=%s",
                    short_key,
                    record.source_token,
                    rect.x(),
                    rect.y(),
                    rect.width(),
                    rect.height(),
                    record.radius,
                    record.path is not None,
                )

            drawn_count += 1

        if drawn_count > 0 and debug_enabled:
            logger.debug(
                "[FLASH] paintEvent END: drew %d sources, overlay=%dx%d",
                drawn_count,
                self.rect().width(),
                self.rect().height(),
            )

        painter.end()


# ==================== GLOBAL ANIMATION COORDINATOR ====================
# Single timer shared across ALL windows - batch computes colors, triggers repaints

class _GlobalFlashCoordinator(QObject):
    """Singleton coordinator for all flash animations across all windows.

    TRUE O(1) ARCHITECTURE:
    - Global flash timing dict: key -> start_time (owned by coordinator)
    - Timer tick pre-computes ALL colors in ONE pass
    - Triggers ONE repaint per window (WindowFlashOverlay)
    - Total: O(k) per tick where k = flashing elements, O(1) per window for repaint
    """
    start_timer_requested = pyqtSignal()
    flush_pending_flashes_requested = pyqtSignal()
    flush_visual_frame_callbacks_requested = pyqtSignal()

    _instance: Optional['_GlobalFlashCoordinator'] = None

    @classmethod
    def get(cls) -> '_GlobalFlashCoordinator':
        if cls._instance is None:
            cls._instance = cls()
        else:
            cls._instance._bind_to_application_thread()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._timer: Optional[QTimer] = None
        self._config = get_flash_config()
        # FIX 1: Single unified flash timing (all keys are scoped, no global/local split)
        self._flash_start_times: Dict[str, float] = {}
        # Pre-computed colors for ALL keys
        self._computed_colors: Dict[str, QColor] = {}
        # PERF: Cache base colors per key (computed ONCE when flash starts, not every tick)
        self._key_base_colors: Dict[str, QColor] = {}
        # Window overlays that need repaint
        self._active_windows: Set[int] = set()  # window_id
        self._tick_count = 0
        self._pending_flash_keys: dict[str, None] = {}
        self._pending_flash_flush_scheduled = False
        self._pending_visual_frame_callbacks: Dict[int, Callable[[], None]] = {}
        self._visual_frame_callback_flush_scheduled = False
        # Pending registrations (widgets not in window hierarchy at registration time)
        self._pending_registrations: List[Tuple[str, Callable[[], Optional['FlashElement']], QWidget, str | None]] = []
        self._trace_next_tick = False
        self.start_timer_requested.connect(
            self._start_timer_in_owner_thread,
            type=Qt.ConnectionType.QueuedConnection,
        )
        self.flush_pending_flashes_requested.connect(
            self._flush_pending_flash_keys,
            type=Qt.ConnectionType.QueuedConnection,
        )
        self.flush_visual_frame_callbacks_requested.connect(
            self._flush_visual_frame_callbacks,
            type=Qt.ConnectionType.QueuedConnection,
        )
        self._bind_to_application_thread()

    def _bind_to_application_thread(self) -> None:
        """Keep the coordinator Qt-affine to the active application thread."""
        app = QCoreApplication.instance()
        if app is None:
            flash_trace("coordinator.no_application")
            return

        app_thread = app.thread()
        try:
            if self.thread() != app_thread:
                self.moveToThread(app_thread)
                flash_trace(
                    "coordinator.move_to_app_thread",
                    coordinator=id(self),
                    app_thread=id(app_thread),
                )
        except RuntimeError:
            flash_trace("coordinator.thread_bind_failed", coordinator=id(self))

    def _ensure_timer(self) -> Optional[QTimer]:
        """Lazy-create timer on first use (after QApplication exists)."""
        self._bind_to_application_thread()
        owner_thread = self.thread()
        current_thread = QThread.currentThread()
        if current_thread != owner_thread:
            flash_trace(
                "coordinator.timer_wrong_thread",
                current=id(current_thread),
                owner=id(owner_thread),
            )
            return None

        if self._timer is not None and self._timer.thread() != owner_thread:
            flash_trace(
                "coordinator.timer_recreate_wrong_thread",
                timer=id(self._timer),
                timer_thread=id(self._timer.thread()),
                owner=id(owner_thread),
            )
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None

        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.setTimerType(Qt.TimerType.PreciseTimer)
            self._timer.timeout.connect(self._on_global_tick)
            flash_trace(
                "coordinator.timer_create",
                timer=id(self._timer),
                owner=id(owner_thread),
            )
        return self._timer

    def _start_timer(self) -> None:
        """Start the timer if not running."""
        self._bind_to_application_thread()
        current_thread = QThread.currentThread()
        owner_thread = self.thread()
        if current_thread != owner_thread:
            flash_trace(
                "coordinator.timer_request_queued",
                current=id(current_thread),
                owner=id(owner_thread),
                active_keys=len(self._flash_start_times),
            )
            self.start_timer_requested.emit()
            return

        self._start_timer_in_owner_thread()

    @pyqtSlot()
    def _start_timer_in_owner_thread(self) -> None:
        """Start the timer from the coordinator's Qt owner thread."""
        timer = self._ensure_timer()
        if timer is None:
            return
        if not timer.isActive():
            timer.start(self._config.frame_ms)
            flash_trace(
                "coordinator.timer_start",
                frame_ms=self._config.frame_ms,
                active_keys=len(self._flash_start_times),
                timer=id(timer),
                active=timer.isActive(),
            )

    def _extract_scope_from_key(self, key: str) -> Optional[str]:
        """Extract orchestrator/parent scope from flash key using canonical parser."""
        try:
            return _extract_orchestrator_scope(key)
        except Exception:
            # Fallback to original key if parsing fails
            return key

    def _get_base_color_for_key(self, key: str) -> QColor:
        """Get base color for flash rendering, using cache for performance.

        PERF: Called once when flash starts, result cached in _key_base_colors.
        Tick loop uses cached value - no per-tick recomputation.
        """
        # Check cache first (O(1) lookup)
        if key in self._key_base_colors:
            return self._key_base_colors[key]

        # Compute and cache
        color = self._compute_base_color_for_key(key)
        self._key_base_colors[key] = color
        return color

    def _compute_base_color_for_key(self, key: str) -> QColor:
        """Compute base color for flash rendering (expensive, cached by caller)."""
        # Empty/None → neutral
        if not key or key == "":
            return self._get_neutral_flash_color()
        # Strip tree:: namespace prefix (used to avoid groupbox key collision)
        if key.startswith("tree::"):
            key = key[6:]  # len("tree::") == 6
        # Heuristic: non-scope keys (no "::" and not path-like) → neutral
        if "::" not in key and not key.startswith("/"):
            return self._get_neutral_flash_color()

        try:
            # Try to use OpenHCS scope coloring if available
            from pyqt_reactive.widgets.shared.scope_color_utils import (
                extract_orchestrator_scope,
                get_scope_color_scheme,
            )

            # Determine if this is a step key or config field key
            parts = key.split("::")
            if len(parts) >= 2:
                token = parts[-1]
                # Use pre-compiled regex (module-level _STEP_TOKEN_RE)
                is_step_token = bool(_STEP_TOKEN_RE.match(token))
                if is_step_token:
                    scope_for_color = key
                else:
                    # Config field - use orchestrator scope so all fields match plate color
                    scope_for_color = extract_orchestrator_scope(key) or key
            else:
                scope_for_color = key

            scheme = get_scope_color_scheme(scope_for_color)
            # If scheme is neutral (scope_id None), use neutral color
            if scheme.scope_id is None:
                return self._get_neutral_flash_color()

            return scheme.accent_qcolor()
        except ImportError:
            # OpenHCS scope coloring not available - use palette-based coloring
            return get_flash_color_from_palette(key)
        except Exception as exc:
            logger.debug("Failed to get scope color for key %s: %s", key, exc)
            return self._get_neutral_flash_color()

    def _get_neutral_flash_color(self) -> QColor:
        """Neutral grey flash color for non-scope keys or errors."""
        return QColor(180, 180, 180)

    def add_pending_registration(
        self,
        key: str,
        element_factory: Callable[[], Optional['FlashElement']],
        widget: QWidget,
        source_id: str | None = None,
    ) -> None:
        """Add a pending registration (widget not in window hierarchy yet)."""
        self._pending_registrations.append((key, element_factory, widget, source_id))
        flash_trace(
            "register.pending_add",
            key=key,
            widget=type(widget).__qualname__,
            source=source_id,
            pending=len(self._pending_registrations),
        )

    def _process_pending_registrations(self) -> None:
        """Process all deferred element registrations (widgets now in window hierarchy).

        RESILIENT: Automatically discards registrations for deleted widgets.
        This handles the case where widgets are deleted and recreated (e.g., function panes).
        """
        if not self._pending_registrations:
            return

        logger.debug(f"[FLASH] _process_pending_registrations: processing {len(self._pending_registrations)} pending")
        still_pending = []
        for key, element_factory, widget, source_id in self._pending_registrations:
            try:
                # Check if widget is still valid (not deleted)
                # Accessing any Qt property will raise RuntimeError if deleted
                _ = widget.isVisible()
                overlay = WindowFlashOverlay.get_for_window(widget)
                if overlay is not None:
                    if overlay.has_element_source(key, source_id):
                        flash_trace(
                            "register.pending_existing_source",
                            key=key,
                            overlay=id(overlay),
                            window=id(overlay._window),
                            source=source_id,
                        )
                        continue
                    element = element_factory()
                    if element is not None:
                        overlay.register_element(element)
                        flash_trace(
                            "register.pending_attached",
                            key=key,
                            overlay=id(overlay),
                            window=id(overlay._window),
                            source=element.source_id,
                        )
                        logger.debug(f"[FLASH] Completed deferred registration: key={key}")
                    else:
                        logger.debug(f"[FLASH] element_factory returned None for key={key}")
                else:
                    logger.debug(f"[FLASH] No overlay for widget, keeping pending: key={key}")
                    flash_trace(
                        "register.pending_wait_overlay",
                        key=key,
                        widget=type(widget).__qualname__,
                    )
                    still_pending.append((key, element_factory, widget, source_id))
            except RuntimeError:
                # Widget was deleted - discard this registration silently
                flash_trace("register.pending_drop_deleted", key=key)
                logger.debug(f"[FLASH] Discarding registration for deleted widget: key={key}")
                continue

        logger.debug(f"[FLASH] _process_pending_registrations: {len(still_pending)} still pending")
        self._pending_registrations = still_pending

    def process_pending_registrations(self) -> None:
        """Public method to process pending registrations.

        Use this before queue_flash to ensure deferred registrations are
        processed immediately (e.g., when navigating via provenance).
        """
        self._process_pending_registrations()

    def active_visual_frame_work_count(self) -> int:
        """Return active visual work owned by the shared frame coordinator."""

        return (
            len(self._flash_start_times)
            + len(self._pending_flash_keys)
            + len(self._pending_visual_frame_callbacks)
        )

    def queue_visual_frame_callback(
        self,
        owner: QObject,
        callback: Callable[[], None],
    ) -> None:
        """Coalesce owner work into the next shared visual frame."""

        self._pending_visual_frame_callbacks[id(owner)] = callback
        flash_trace(
            "visual_frame.callback_queued",
            owner=type(owner).__qualname__,
            pending=len(self._pending_visual_frame_callbacks),
            active_flashes=len(self._flash_start_times),
        )

        if self._flash_start_times or self._pending_flash_keys or self._active_windows:
            self._start_timer()
            return

        if self._visual_frame_callback_flush_scheduled:
            return
        self._visual_frame_callback_flush_scheduled = True
        self._bind_to_application_thread()
        if QThread.currentThread() != self.thread():
            self.flush_visual_frame_callbacks_requested.emit()
            return
        QTimer.singleShot(0, self._flush_visual_frame_callbacks)

    @pyqtSlot()
    def _flush_visual_frame_callbacks(self) -> None:
        callbacks = tuple(self._pending_visual_frame_callbacks.values())
        self._pending_visual_frame_callbacks.clear()
        self._visual_frame_callback_flush_scheduled = False
        for callback in callbacks:
            try:
                callback()
            except Exception:
                logger.exception("Visual frame callback failed")

    def _schedule_pending_flash_flush(self) -> None:
        if self._pending_flash_flush_scheduled:
            return
        self._pending_flash_flush_scheduled = True
        self._bind_to_application_thread()
        if QThread.currentThread() != self.thread():
            self.flush_pending_flashes_requested.emit()
            return
        QTimer.singleShot(0, self._flush_pending_flash_keys)

    def _enqueue_flash_keys(self, keys: Iterable[str]) -> None:
        added = 0
        for key in keys:
            if not key:
                continue
            if key not in self._pending_flash_keys:
                added += 1
            self._pending_flash_keys[key] = None
        if added:
            flash_trace(
                "queue.pending",
                added=added,
                pending=len(self._pending_flash_keys),
            )
        if self._pending_flash_keys:
            self._schedule_pending_flash_flush()

    def _commit_flash_keys(self, keys: Iterable[str], *, timestamp: float) -> None:
        unique_keys = tuple(dict.fromkeys(key for key in keys if key))
        if not unique_keys:
            return

        self._process_pending_registrations()

        for key in unique_keys:
            self._flash_start_times[key] = timestamp

        keys_set = set(unique_keys)
        for window_id, overlay in WindowFlashOverlay._overlays.items():
            if self._overlay_flash_keys(overlay, keys_set):
                self._active_windows.add(window_id)

        self._trace_next_tick = True
        self._start_timer()
        logger.debug(
            "[FLASH] committed flash batch: keys=%s active_windows=%s",
            len(unique_keys),
            len(self._active_windows),
        )

    @pyqtSlot()
    def _flush_pending_flash_keys(self) -> None:
        keys = tuple(self._pending_flash_keys)
        self._pending_flash_keys.clear()
        self._pending_flash_flush_scheduled = False
        if not keys:
            return
        self._commit_flash_keys(keys, timestamp=time.perf_counter())
        flash_trace(
            "queue.flush",
            keys=len(keys),
            active=len(self._flash_start_times),
        )

    def queue_flash_batch(self, keys: Iterable[str]) -> None:
        """Queue multiple flashes with shared timestamp - perfect sync.

        Commits at the next event-loop turn so independent owners participating
        in one UI mutation share one timestamp and one timer start.
        """
        self._enqueue_flash_keys(keys)

    def queue_flash(self, key: str, window: Optional[QWidget] = None, timestamp: Optional[float] = None) -> None:
        """Start or retrigger flash for key (global API).

        Args:
            key: The flash key
            window: Optional window widget (for window-level overlay registration)
            timestamp: Optional shared timestamp for batch sync (all keys in batch use same time)
        """
        if timestamp is None:
            self._enqueue_flash_keys((key,))
        else:
            self._commit_flash_keys((key,), timestamp=timestamp)
        flash_trace(
            "queue.global",
            key=key,
            pending=len(self._pending_flash_keys),
            active=len(self._flash_start_times),
        )
        logger.debug("[FLASH] queue_flash: key=%s pending=%s", key, timestamp is None)

    def _maybe_stop_timer(self) -> None:
        """Stop timer if no active animations."""
        if (not self._active_windows and
            not self._flash_start_times and
            self._timer and self._timer.isActive()):
            self._timer.stop()
            for overlay in WindowFlashOverlay._overlays.values():
                overlay._last_flash_update_region = QRegion()
                overlay._last_flash_mask_region = QRegion()
                overlay.clearMask()
                if overlay.isVisible():
                    overlay.hide()

    def get_computed_color(self, key: str) -> Optional[QColor]:
        """Get pre-computed color for key. O(1) dict lookup."""
        return self._computed_colors.get(key)

    @staticmethod
    def _key_matches_hierarchical_prefix(key: str, prefix: str) -> bool:
        """Return whether an ObjectState flash key is at or below a prefix."""
        if key == prefix or key.startswith(f"{prefix}::"):
            return True
        key_scope, key_path = _GlobalFlashCoordinator._split_scoped_object_state_key(key)
        prefix_scope, prefix_path = _GlobalFlashCoordinator._split_scoped_object_state_key(prefix)
        if prefix_scope is not None and key_scope != prefix_scope:
            return False
        if not key_path or not prefix_path:
            return False
        return DottedFieldPath(prefix_path).contains_path(key_path)

    @staticmethod
    def _split_scoped_object_state_key(key: str) -> tuple[str | None, str]:
        """Split an optional scope prefix from an ObjectState flash path."""

        scope, separator, path = key.rpartition("::")
        if not separator:
            return None, key
        return scope, path

    @staticmethod
    def _hierarchical_prefix_candidates(key: str) -> tuple[str, ...]:
        """Return possible ObjectState ancestor keys for one scoped flash key."""
        scope, separator, path = key.rpartition("::")
        scoped = bool(separator)
        if not scoped:
            path = key
        if not path:
            return (key,)

        candidates: list[str] = []
        seen: set[str] = set()
        if scoped:
            candidates.append(scope)
            seen.add(scope)

        for index, char in enumerate(path):
            if char not in ".[" or index == 0:
                continue
            candidate_path = path[:index]
            candidate = f"{scope}::{candidate_path}" if scoped else candidate_path
            if candidate not in seen:
                candidates.append(candidate)
                seen.add(candidate)

        if key not in seen:
            candidates.append(key)
        return tuple(candidates)

    def get_computed_color_for_object_state_path(self, object_state_path: str) -> Optional[QColor]:
        """Return the strongest active color for one ObjectState path."""
        exact = self._computed_colors.get(object_state_path)
        if exact is not None:
            return exact
        matches = [
            color
            for key, color in self._computed_colors.items()
            if self._key_matches_hierarchical_prefix(key, object_state_path)
        ]
        if not matches:
            return None
        return max(matches, key=lambda color: color.alpha())

    def _overlay_has_hierarchical_flash_target(
        self,
        overlay: 'WindowFlashOverlay',
        key: str,
    ) -> bool:
        """Return whether an overlay has a delegate element for this key prefix."""
        hierarchical_keys = overlay._hierarchical_delegate_keys
        return any(
            candidate != key and candidate in hierarchical_keys
            for candidate in self._hierarchical_prefix_candidates(key)
        )

    def _overlay_flash_keys(
        self,
        overlay: 'WindowFlashOverlay',
        keys: Set[str],
    ) -> Set[str]:
        """Return active keys that have exact or hierarchical targets in an overlay."""
        overlay_keys = keys & overlay._elements.keys()
        hierarchical_keys = overlay._hierarchical_delegate_keys
        if not hierarchical_keys:
            return overlay_keys

        for key in keys:
            for candidate in self._hierarchical_prefix_candidates(key):
                if candidate == key:
                    continue
                if candidate in hierarchical_keys:
                    overlay_keys.add(candidate)
        return overlay_keys

    def _update_delegate_element(self, element: FlashElement) -> None:
        """Repaint only the delegate-owned item rect for a flashing list/tree row."""
        widget = element.delegate_widget
        if widget is None or element.get_model_index is None:
            return

        try:
            index = element.get_model_index()
            if index is None or not index.isValid():
                return

            viewport = widget.viewport()
            if viewport is None:
                return

            visual_rect = widget.visualRect(index)
            if not visual_rect.isValid():
                return

            update_rect = visual_rect.intersected(viewport.rect())
            if not update_rect.isEmpty():
                viewport.update(update_rect)
        except (RuntimeError, AttributeError):
            pass

    def _update_overlay_for_keys(self, overlay: 'WindowFlashOverlay', keys: Set[str]) -> bool:
        """Update delegate rows directly and report whether overlay paint is needed."""
        needs_overlay_paint = False
        updated_delegate_sources: Set[str] = set()
        for key in keys:
            for element in overlay._elements.get(key, []):
                if element.skip_overlay_paint:
                    if element.source_id in updated_delegate_sources:
                        continue
                    if element.source_id is not None:
                        updated_delegate_sources.add(element.source_id)
                    self._update_delegate_element(element)
                else:
                    needs_overlay_paint = True
        return needs_overlay_paint

    def _arm_overlay_for_paint(self, overlay: 'WindowFlashOverlay') -> tuple[float, float, float]:
        """Keep the window-level overlay paintable and above dynamic form content."""
        geometry_ms = 0.0
        show_ms = 0.0
        raise_ms = 0.0
        target_geometry = overlay._window.rect()
        if overlay.geometry() != target_geometry:
            started = time.perf_counter()
            overlay.setGeometry(target_geometry)
            geometry_ms = (time.perf_counter() - started) * 1000.0
            overlay._needs_raise = True
        if not overlay.isVisible():
            overlay._needs_raise = True
        if overlay.isVisible() and overlay._needs_raise:
            started = time.perf_counter()
            overlay.raise_()
            raise_ms = (time.perf_counter() - started) * 1000.0
            overlay._needs_raise = False
        return geometry_ms, show_ms, raise_ms

    def _on_global_tick(self) -> None:
        """Global tick - BATCH compute ALL colors, then trigger ONE repaint per window.

        TRUE O(1) PER WINDOW:
        - Compute colors for all active keys: O(k)
        - Trigger window overlay repaints: O(w) where w = number of windows
        - Each overlay paintEvent: O(k_window) elements
        """
        tick_started = time.perf_counter()
        now = time.perf_counter()
        self._tick_count += 1

        # ==================== BATCH COLOR COMPUTATION ====================
        # FIX 1: Single unified color computation (all keys are scoped)
        self._computed_colors.clear()
        expired_keys = []

        # Compute colors for ALL keys (no global/local distinction)
        total_duration_s = (
            self._config.fade_in_s + self._config.hold_s + self._config.fade_out_s
        )
        for key, start_time in self._flash_start_times.items():
            base_color = self._get_base_color_for_key(key)
            if now - start_time >= total_duration_s:
                expired_keys.append(key)
                continue
            color = compute_flash_color_at_time(
                start_time, now, config=self._config, base_color=base_color
            )
            if color and color.alpha() > 0:
                self._computed_colors[key] = color

        # Prune expired keys and their cached base colors
        for key in expired_keys:
            del self._flash_start_times[key]
            self._key_base_colors.pop(key, None)  # Clean up color cache

        # Run coalesced non-flash visual work inside the same frame boundary
        # before overlay update requests are issued.
        self._flush_visual_frame_callbacks()

        # ==================== TRIGGER WINDOW OVERLAY REPAINTS ====================
        # FIX 1 & 2: Simplified single-path repaint (all keys scoped, no dirty tracking complexity)
        active_windows_this_frame = set()
        computed_keys = set(self._computed_colors.keys())
        trace_next_tick = self._trace_next_tick
        overlay_paint_count = 0
        overlay_visible_key_count = 0
        overlay_rect_count = 0
        match_elapsed_ms = 0.0
        delegate_elapsed_ms = 0.0
        paint_request_elapsed_ms = 0.0
        arm_elapsed_ms = 0.0
        arm_geometry_ms = 0.0
        arm_show_ms = 0.0
        arm_raise_ms = 0.0
        request_update_elapsed_ms = 0.0
        if trace_next_tick:
            self._trace_next_tick = False

        # Find windows that had keys expire this frame (need final clear repaint)
        expired_keys_by_window: Dict[int, Set[str]] = {}
        if expired_keys:
            expired_keys_set = set(expired_keys)
            for window_id, overlay in WindowFlashOverlay._overlays.items():
                # PERFORMANCE FIX: Skip hidden windows in clear detection too
                try:
                    if not overlay._window.isVisible():
                        continue
                except RuntimeError:
                    continue  # Window deleted

                expired_window_keys = self._overlay_flash_keys(
                    overlay,
                    expired_keys_set,
                )
                if expired_window_keys:
                    expired_keys_by_window[window_id] = expired_window_keys

        for window_id, overlay in WindowFlashOverlay._overlays.items():
            # PERFORMANCE FIX: Skip hidden windows (don't waste CPU painting invisible windows)
            try:
                if not overlay._window.isVisible():
                    continue
            except RuntimeError:
                # Window deleted
                continue

            # Find which active keys have exact or hierarchical targets here.
            phase_started = time.perf_counter()
            window_keys = self._overlay_flash_keys(overlay, computed_keys)
            match_elapsed_ms += (time.perf_counter() - phase_started) * 1000.0

            if window_keys:
                active_windows_this_frame.add(window_id)
                phase_started = time.perf_counter()
                needs_overlay_paint = self._update_overlay_for_keys(overlay, window_keys)
                delegate_elapsed_ms += (time.perf_counter() - phase_started) * 1000.0

                # Only update overlay if there are elements that need it
                if needs_overlay_paint:
                    try:
                        phase_started = time.perf_counter()
                        geometry_ms, show_ms, raise_ms = self._arm_overlay_for_paint(overlay)
                        arm_elapsed_ms += (time.perf_counter() - phase_started) * 1000.0
                        arm_geometry_ms += geometry_ms
                        arm_show_ms += show_ms
                        arm_raise_ms += raise_ms
                        phase_started = time.perf_counter()
                        visible_keys, rects = overlay.request_flash_update_for_keys(window_keys)
                        request_update_elapsed_ms += (time.perf_counter() - phase_started) * 1000.0
                        paint_request_elapsed_ms = arm_elapsed_ms + request_update_elapsed_ms
                        if rects:
                            overlay_paint_count += 1
                            overlay_visible_key_count += visible_keys
                            overlay_rect_count += rects
                    except RuntimeError:
                        logger.debug(f"[FLASH] Window {window_id} deleted during animation")

        if trace_next_tick:
            flash_trace(
                "coordinator.tick",
                computed=len(computed_keys),
                expired=len(expired_keys),
                active_windows=len(active_windows_this_frame),
                overlays=len(WindowFlashOverlay._overlays),
                elapsed_ms=f"{(time.perf_counter() - tick_started) * 1000.0:.3f}",
                keys=sorted(computed_keys),
            )

        self._active_windows = active_windows_this_frame

        # CRITICAL: Final clear repaint for windows where keys expired
        # Ensures flash is fully cleared even if no other animations active
        for window_id, expired_window_keys in expired_keys_by_window.items():
            overlay = WindowFlashOverlay._overlays.get(window_id)
            if overlay:
                # PERFORMANCE FIX: Skip hidden windows
                try:
                    if not overlay._window.isVisible():
                        continue
                except RuntimeError:
                    continue  # Window deleted

                phase_started = time.perf_counter()
                needs_overlay_paint = self._update_overlay_for_keys(overlay, expired_window_keys)
                delegate_elapsed_ms += (time.perf_counter() - phase_started) * 1000.0
                if needs_overlay_paint:
                    try:
                        phase_started = time.perf_counter()
                        geometry_ms, show_ms, raise_ms = self._arm_overlay_for_paint(overlay)
                        arm_elapsed_ms += (time.perf_counter() - phase_started) * 1000.0
                        arm_geometry_ms += geometry_ms
                        arm_show_ms += show_ms
                        arm_raise_ms += raise_ms
                        phase_started = time.perf_counter()
                        visible_keys, rects = overlay.request_flash_update_for_keys(
                            expired_window_keys,
                            clear_after=True,
                        )
                        request_update_elapsed_ms += (time.perf_counter() - phase_started) * 1000.0
                        paint_request_elapsed_ms = arm_elapsed_ms + request_update_elapsed_ms
                        if rects:
                            overlay_paint_count += 1
                            overlay_visible_key_count += visible_keys
                            overlay_rect_count += rects
                    except RuntimeError:
                        raise

        tick_elapsed_ms = (time.perf_counter() - tick_started) * 1000.0
        if TimeTravelProfiler.enabled() and (
            tick_elapsed_ms >= 4.0 or self._tick_count % 10 == 0
        ):
            logging.getLogger(TimeTravelProfiler.logger_name).info(
                "TT_PHASE name=%s elapsed_ms=%.3f computed=%r expired=%r active_windows=%r overlays=%r overlay_paints=%r visible_keys=%r rects=%r match_ms=%.3f delegate_ms=%.3f paint_request_ms=%.3f arm_ms=%.3f arm_geometry_ms=%.3f arm_show_ms=%.3f arm_raise_ms=%.3f request_update_ms=%.3f",
                "pyqt.flash.coordinator_tick",
                tick_elapsed_ms,
                len(computed_keys),
                len(expired_keys),
                len(active_windows_this_frame),
                len(WindowFlashOverlay._overlays),
                overlay_paint_count,
                overlay_visible_key_count,
                overlay_rect_count,
                match_elapsed_ms,
                delegate_elapsed_ms,
                paint_request_elapsed_ms,
                arm_elapsed_ms,
                arm_geometry_ms,
                arm_show_ms,
                arm_raise_ms,
                request_update_elapsed_ms,
            )

        # Diagnostic logging - show REAL work being done
        if self._tick_count % 30 == 0:
            logger.debug(f"[FLASH PERF] tick={self._tick_count} colors={len(self._computed_colors)} overlays_painted={overlay_paint_count} total_overlays={len(WindowFlashOverlay._overlays)}")

        # Stop timer if nothing active
        self._maybe_stop_timer()


class VisualUpdateMixin:
    """Mixin providing batched visual updates at 60fps.

    TRUE O(1) ARCHITECTURE:
    - Flash timing owned by global coordinator
    - flash colors come from pre-computed ObjectState-path lookups (O(1) exact,
      bounded ancestor lookup for delegate rows)
    - Window-level overlay renders ALL elements in ONE paintEvent
    """

    _text_timer: QTimer
    _text_update_pending: bool

    # Optional scope_id from implementing classes (e.g., ParameterFormManager)
    scope_id: Optional[str]

    def _init_visual_update_mixin(self) -> None:
        """Initialize visual update state. Call in __init__."""
        self._text_update_pending = False
        # Track all flash registrations so they can be re-registered after overlay cleanup
        self._flash_registrations: List[
            Tuple[
                str,
                Callable[[str], FlashElement],
                QWidget,
                Optional[Callable[[str], str | None]],
                str | None,
            ]
        ] = []
        self._flash_registration_lifecycle_keys: Set[Tuple[int, str, int, str | None]] = set()

        # Text update timer (per-widget, debounced)
        self._text_timer = QTimer()
        self._text_timer.setSingleShot(True)
        self._text_timer.timeout.connect(self._execute_text_update_batch)

    def flash_scope_id(self) -> str | None:
        """Return the optional scope prefix for local flash keys."""
        return None

    def flash_masks_descendant_leaf_widgets(self) -> bool:
        """Return True when standard container flashes mask leaf descendants."""
        return False

    def flash_unmasked_widgets(self) -> tuple[QWidget, ...]:
        """Return descendant widgets excluded from standard descendant masks."""
        return ()

    def flash_title_mask_widgets(self) -> tuple[QWidget, ...]:
        """Return title-row widgets that should be masked during container flashes."""
        return ()

    def _get_scoped_flash_key(self, key: str) -> str:
        """Get flash key with scope prefix to prevent cross-window contamination.

        Automatically prepends scope_id if available (ParameterFormManager pattern).
        Prevents flashes from leaking between windows editing different scopes.

        Example:
            plate1 window: "step_0" → "plate1::step_0"
            plate2 window: "step_0" → "plate2::step_0"
        """
        scope_id = self.flash_scope_id()
        if scope_id:
            return f"{scope_id}::{key}"
        return key

    def _register_flash_element_internal(
        self,
        key: str,
        element_factory: Callable[[str], FlashElement],
        widget: QWidget,
        *,
        record: bool = True,
        lifecycle_widgets: tuple[QWidget | None, ...] = (),
        source_id_factory: Optional[Callable[[str], str | None]] = None,
    ) -> None:
        """Internal helper for flash element registration. DRY for all element types.

        FAIL-LOUD: No exception handling - registration failures should crash.
        """
        scoped_key = self._get_scoped_flash_key(key)
        source_id = (
            source_id_factory(scoped_key)
            if source_id_factory is not None
            else None
        )
        overlay = WindowFlashOverlay.get_for_window(widget) if widget is not None else None
        element: FlashElement | None = None
        if overlay is None or not overlay.has_element_source(scoped_key, source_id):
            element = element_factory(scoped_key)
            if source_id is None:
                source_id = element.source_id

        if record:
            # Avoid duplicate bookkeeping for the same widget/key pair
            already_recorded = any(
                existing_key == key
                and existing_widget is widget
                and existing_source_id == source_id
                for (
                    existing_key,
                    _,
                    existing_widget,
                    _existing_source_factory,
                    existing_source_id,
                ) in self._flash_registrations
            )
            if not already_recorded:
                self._flash_registrations.append(
                    (key, element_factory, widget, source_id_factory, source_id)
                )
            self._connect_flash_lifecycle_cleanup(
                key,
                scoped_key,
                source_id,
                widget,
                lifecycle_widgets,
            )

        if widget is not None:
            if overlay is not None:
                if element is None:
                    flash_trace(
                        "register.existing_source",
                        key=key,
                        scoped=scoped_key,
                        widget=type(widget).__qualname__,
                        window=id(overlay._window),
                        overlay=id(overlay),
                        source=source_id,
                    )
                    return
                overlay.register_element(element)
                flash_trace(
                    "register.immediate",
                    key=key,
                    scoped=scoped_key,
                    widget=type(widget).__qualname__,
                    window=id(overlay._window),
                    overlay=id(overlay),
                    source=source_id,
                )
                logger.debug(f"[FLASH] Immediate registration: key={scoped_key}")
            else:
                coordinator = _GlobalFlashCoordinator.get()
                coordinator.add_pending_registration(
                    scoped_key,
                    lambda: element_factory(scoped_key),
                    widget,
                    source_id,
                )
                flash_trace(
                    "register.deferred_no_overlay",
                    key=key,
                    scoped=scoped_key,
                    widget=type(widget).__qualname__,
                    source=source_id,
                )
                logger.debug(f"[FLASH] Deferred registration (pending): key={scoped_key}, no overlay yet")

    def _connect_flash_lifecycle_cleanup(
        self,
        key: str,
        scoped_key: str,
        source_id: str | None,
        owner_widget: QWidget,
        lifecycle_widgets: tuple[QWidget | None, ...],
    ) -> None:
        """Remove flash registrations when any widget they close over is destroyed."""
        registrations = self._flash_registrations
        lifecycle_keys = self._flash_registration_lifecycle_keys
        widgets: list[QWidget] = []
        seen_widget_ids: set[int] = set()
        for candidate in (owner_widget, *lifecycle_widgets):
            if candidate is None or sip.isdeleted(candidate):
                continue
            candidate_id = id(candidate)
            if candidate_id in seen_widget_ids:
                continue
            seen_widget_ids.add(candidate_id)
            widgets.append(candidate)

        for lifecycle_widget in widgets:
            lifecycle_key = (id(lifecycle_widget), key, id(owner_widget), source_id)
            if lifecycle_key in self._flash_registration_lifecycle_keys:
                continue
            self._flash_registration_lifecycle_keys.add(lifecycle_key)
            lifecycle_widget.destroyed.connect(
                partial(
                    VisualUpdateMixin._cleanup_flash_registration,
                    registrations,
                    lifecycle_keys,
                    lifecycle_key,
                    scoped_key,
                )
            )

    @staticmethod
    def _cleanup_flash_registration(
        registrations: List[
            Tuple[
                str,
                Callable[[str], FlashElement],
                QWidget,
                Optional[Callable[[str], str | None]],
                str | None,
            ]
        ],
        lifecycle_keys: Set[Tuple[int, str, int, str | None]],
        lifecycle_key: Tuple[int, str, int, str | None],
        scoped_key: str,
        _destroyed_object: object | None = None,
    ) -> None:
        """Drop recorded and overlay flash elements for a destroyed dependency."""
        lifecycle_keys.discard(lifecycle_key)
        _, key, owner_widget_id, source_id = lifecycle_key
        registrations[:] = [
            (registered_key, element_factory, widget, source_id_factory, registered_source_id)
            for (
                registered_key,
                element_factory,
                widget,
                source_id_factory,
                registered_source_id,
            ) in registrations
            if not (
                registered_key == key
                and id(widget) == owner_widget_id
                and registered_source_id == source_id
            )
        ]
        for overlay in list(WindowFlashOverlay._overlays.values()):
            overlay.unregister_element_source(scoped_key, source_id)

    def register_flash_groupbox(self, key: str, groupbox: 'QWidget') -> None:
        """Register a groupbox for flash rendering."""
        self._register_flash_element_internal(
            key,
            lambda k: create_groupbox_element(k, groupbox),  # type: ignore
            groupbox,
            source_id_factory=lambda k: groupbox_flash_source_id(k, groupbox),
        )

    def register_flash_groupbox_full(self, key: str, groupbox: 'QWidget') -> None:
        """Register a groupbox for full-rect flash rendering.

        Uses the widget's full geometry (no margin-top offset).
        """
        self._register_flash_element_internal(
            key,
            lambda k: create_groupbox_element(k, groupbox, use_full_rect=True),  # type: ignore
            groupbox,
            source_id_factory=lambda k: groupbox_flash_source_id(k, groupbox, use_full_rect=True),
        )

    def register_flash_widget_rect(self, key: str, widget: QWidget) -> None:
        """Register a widget for direct full-rect flash rendering."""
        self._register_flash_element_internal(
            key,
            lambda k: create_widget_rect_element(k, widget),
            widget,
            source_id_factory=lambda _k: widget_rect_flash_source_id(widget),
        )

    def register_flash_table_cell_rect(
        self,
        key: str,
        target: "StructuralTableCellTarget",
    ) -> None:
        """Register an item-backed table cell for direct flash rendering."""
        self._register_flash_element_internal(
            key,
            lambda k: create_table_cell_element(k, target),
            target.table.viewport(),
            source_id_factory=lambda _k: table_cell_flash_source_id(target),
        )

    def register_flash_masked_container(
        self,
        key: str,
        container: QWidget,
        mask_rects: Callable[[QWidget], Iterable[Tuple[QRect, bool]]],
        *,
        label_widget: Optional[QWidget] = None,
        layout_watch_widgets: Iterable[QWidget] = (),
    ) -> None:
        """Register a container flash with structural descendant masks."""
        self._register_flash_element_internal(
            key,
            lambda k: create_structural_masked_container_element(
                k,
                container,
                mask_rects,
                layout_watch_widgets=layout_watch_widgets,
            ),
            container,
            lifecycle_widgets=(label_widget,),
            source_id_factory=lambda k: groupbox_flash_source_id(
                k,
                container,
                inverse_masking=True,
            ),
        )

    def register_flash_tree_item(self, key: str, tree: 'QTreeWidget', get_index: Callable[[], Any]) -> None:
        """Register a tree item for flash rendering."""
        self._register_flash_element_internal(
            key,
            lambda k: create_tree_item_element(k, tree, get_index),
            tree
        )

    def register_flash_leaf(self, key: str, groupbox: 'QWidget', leaf_widget: 'QWidget', label_widget: Optional['QWidget'] = None) -> None:
        """Register a leaf field for INVERSE flash rendering.

        Flashes the groupbox INCLUDING all sibling fields, but masks out:
        - The groupbox title
        - The specific leaf widget that changed
        - The label associated with the leaf widget (if provided)

        This highlights "all fields that inherited the change" while keeping
        the actual changed widget visible.

        Uses the unified create_groupbox_element with leaf_widget and label_widget parameters.
        """
        logger.debug(f"[FLASH TRAIL] register_flash_leaf: key={key}, groupbox={type(groupbox).__name__}, leaf_widget={type(leaf_widget).__name__}, label_widget={type(label_widget).__name__ if label_widget else None}")
        self._register_flash_element_internal(
            key,
            lambda k: create_groupbox_element(k, groupbox, leaf_widget=leaf_widget, label_widget=label_widget),  # type: ignore
            groupbox,
            lifecycle_widgets=(leaf_widget, label_widget),
            source_id_factory=lambda k: groupbox_flash_source_id(
                k,
                groupbox,
                leaf_widget=leaf_widget,
                label_widget=label_widget,
            ),
        )

    def reregister_flash_elements(self) -> None:
        """Re-register all previously registered flash elements (after overlay cleanup)."""
        if not self._flash_registrations:
            return
        for key, element_factory, widget, source_id_factory, _source_id in list(self._flash_registrations):
            self._register_flash_element_internal(
                key,
                element_factory,
                widget,
                record=False,
                source_id_factory=source_id_factory,
            )

    def queue_visual_update(self) -> None:
        """Queue text/placeholder update (debounced)."""
        self._text_update_pending = True
        if not self._text_timer.isActive():
            self._text_timer.start(16)

    def queue_flash(self, key: str, timestamp: Optional[float] = None) -> None:
        """Start or retrigger flash for key (GLOBAL - all windows with this key flash).

        Args:
            key: The flash key
            timestamp: Optional shared timestamp for batch sync (all keys in batch use same time)
        """
        coordinator = _GlobalFlashCoordinator.get()
        window = self.window() if isinstance(self, QWidget) else None
        coordinator.queue_flash(key, window, timestamp=timestamp)

    def queue_flash_batch(self, keys: Iterable[str]) -> None:
        """Start multiple global flashes with one coordinator registration/timer pass."""
        unique_keys = list(dict.fromkeys(keys))
        if not unique_keys:
            return
        _GlobalFlashCoordinator.get().queue_flash_batch(unique_keys)

    def queue_flash_local(self, key: str, *, scoped: bool = True) -> None:
        """Start flash for key in THIS WINDOW ONLY.

        Unlike queue_flash(), this only flashes the element in the current window's overlay.
        Used for:
        - Scroll-to-section navigation (local feedback)
        - ParameterFormManager resolved value changes (scope-aware, window-local)

        Key is automatically scoped to prevent cross-window contamination.
        """
        scoped_key = self._get_scoped_flash_key(key) if scoped else key
        flash_trace(
            "queue.local.attempt",
            key=key,
            scoped=scoped_key,
            manager_scope=self.flash_scope_id(),
        )

        window = self.window() if isinstance(self, QWidget) else None
        if window is None:
            flash_trace("queue.local.skip_no_window", key=key, scoped=scoped_key)
            logger.debug(
                "[FLASH] queue_flash_local skipped: key=%s scoped=%s no window",
                key,
                scoped_key,
            )
            return

        window_id = id(window)
        coordinator = _GlobalFlashCoordinator.get()

        # Process pending registrations FIRST (elements may not be registered yet)
        coordinator._process_pending_registrations()

        overlay = WindowFlashOverlay._overlays.get(window_id)
        if overlay is None:
            flash_trace(
                "queue.local.skip_no_overlay",
                key=key,
                scoped=scoped_key,
                window=window_id,
                overlays=len(WindowFlashOverlay._overlays),
            )
            logger.debug(
                "[FLASH] queue_flash_local skipped: key=%s scoped=%s no overlay for window %s",
                key,
                scoped_key,
                window_id,
            )
            return

        # Check if scoped key exists in this window's overlay, either as an
        # exact paint target or as a hierarchy-row prefix subscriber.
        if (
            scoped_key not in overlay._elements
            and not coordinator._overlay_has_hierarchical_flash_target(
                overlay,
                scoped_key,
            )
        ):
            flash_trace(
                "queue.local.skip_missing_key",
                key=key,
                scoped=scoped_key,
                window=window_id,
                overlay=id(overlay),
                available=list(overlay._elements.keys()),
            )
            logger.debug(
                "[FLASH] queue_flash_local skipped: key=%s scoped=%s missing; available=%s",
                key,
                scoped_key,
                list(overlay._elements.keys()),
            )
            return

        is_new_flash = (
            scoped_key not in coordinator._flash_start_times
            and scoped_key not in coordinator._pending_flash_keys
        )
        coordinator._enqueue_flash_keys((scoped_key,))

        flash_trace(
            "queue.local.queued",
            key=key,
            scoped=scoped_key,
            window=window_id,
            overlay=id(overlay),
            new=is_new_flash,
            elements=len(overlay._elements.get(scoped_key, ())),
            active_keys=len(coordinator._flash_start_times),
        )
        logger.debug(
            "[FLASH] queue_flash_local queued: key=%s scoped=%s window=%s",
            key,
            scoped_key,
            window_id,
        )

    def queue_flash_local_batch(self, keys: Iterable[str], *, scoped: bool = True) -> None:
        """Start multiple local flashes with one pending-registration and timer pass."""
        unique_keys = tuple(dict.fromkeys(keys))
        if not unique_keys:
            return

        scoped_keys = tuple(
            self._get_scoped_flash_key(key) if scoped else key
            for key in unique_keys
        )
        window = self.window() if isinstance(self, QWidget) else None
        if window is None:
            flash_trace(
                "queue.local.batch_skip_no_window",
                count=len(scoped_keys),
                manager_scope=self.flash_scope_id(),
            )
            return

        window_id = id(window)
        coordinator = _GlobalFlashCoordinator.get()
        coordinator._process_pending_registrations()

        overlay = WindowFlashOverlay._overlays.get(window_id)
        if overlay is None:
            flash_trace(
                "queue.local.batch_skip_no_overlay",
                count=len(scoped_keys),
                window=window_id,
                overlays=len(WindowFlashOverlay._overlays),
            )
            return

        queueable_keys: list[str] = []
        for scoped_key in scoped_keys:
            if (
                scoped_key in overlay._elements
                or coordinator._overlay_has_hierarchical_flash_target(
                    overlay,
                    scoped_key,
                )
            ):
                queueable_keys.append(scoped_key)

        if not queueable_keys:
            flash_trace(
                "queue.local.batch_skip_missing",
                requested=len(scoped_keys),
                window=window_id,
                overlay=id(overlay),
            )
            return

        new_count = 0
        for scoped_key in queueable_keys:
            is_new_flash = (
                scoped_key not in coordinator._flash_start_times
                and scoped_key not in coordinator._pending_flash_keys
            )
            if is_new_flash:
                new_count += 1

        coordinator._enqueue_flash_keys(queueable_keys)

        flash_trace(
            "queue.local.batch_queued",
            requested=len(scoped_keys),
            queued=len(queueable_keys),
            new=new_count,
            window=window_id,
            overlay=id(overlay),
            active_keys=len(coordinator._flash_start_times),
        )

    def get_flash_color_for_object_state_path(
        self,
        object_state_path: str,
    ) -> Optional[QColor]:
        """Get the current flash color for an ObjectState-backed delegate row."""
        return _GlobalFlashCoordinator.get().get_computed_color_for_object_state_path(
            object_state_path
        )

    def _execute_text_update_batch(self) -> None:
        """Execute pending text update."""
        if self._text_update_pending:
            self._text_update_pending = False
            self._execute_text_update()
            self._visual_repaint()

    def _execute_text_update(self) -> None:
        """Execute text/placeholder update. Override in subclass."""
        pass

    def _visual_repaint(self) -> None:
        """Repaint visual surfaces after role-only updates. Override in subclass."""
        pass


# Backwards compatibility
FlashMixin = VisualUpdateMixin
