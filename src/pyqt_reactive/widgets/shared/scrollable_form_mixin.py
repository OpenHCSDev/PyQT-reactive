"""
Mixin for widgets that manage a ParameterFormManager with a scroll area.

Provides common functionality for scrolling to sections in the form.
Used by ConfigWindow and StepParameterEditorWidget.
"""
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from PyQt6.QtWidgets import QScrollArea, QWidget

from pyqt_reactive.services.window_navigation import (
    FormFieldWindowNavigationDriver,
    NavigationWaitReason,
    RegisteredWindowNavigationReadiness,
    RegisteredWindowNavigationRequest,
    WindowNavigationDriver,
)

if TYPE_CHECKING:
    from pyqt_reactive.widgets.structural_table import StructuralFlashTarget

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScrollTarget:
    """Resolved form navigation target."""

    field_name: str
    leaf_name: str
    section_path: str
    target_widget: QWidget
    groupbox_widget: Optional[QWidget]
    current_manager: Any
    is_field: bool
    structural_flash_target: Optional["StructuralFlashTarget"] = None


@dataclass(frozen=True)
class ScrollViewport:
    """Snapshot of scroll-area geometry used to compute navigation."""

    content_widget: QWidget
    viewport_height: int
    viewport_top: int
    viewport_bottom: int
    vertical_scroll_bar: Any


class ScrollableFormWindowNavigationDriver(FormFieldWindowNavigationDriver):
    """Field navigation driver that waits for scrollable-form layout readiness."""

    def __init__(self, owner: "ScrollableFormMixin") -> None:
        super().__init__(
            select_field=owner.select_and_scroll_to_field,
            form_manager=lambda: owner.form_manager,
        )
        self._owner = owner
        self.stable_geometry_sample_count = 2
        self._last_geometry_signature = None
        self._stable_geometry_samples = 0

    def readiness(
        self,
        request: RegisteredWindowNavigationRequest,
    ) -> RegisteredWindowNavigationReadiness:
        readiness = super().readiness(request)
        if not readiness.window_alive or readiness.needs_wait:
            return readiness
        if request.field_path is None:
            return readiness

        if self._owner.scroll_area is None:
            return RegisteredWindowNavigationReadiness(
                wait_reason=NavigationWaitReason.LAYOUT,
            )

        target, is_fallback = self._owner._resolve_navigation_scroll_target(
            request.field_path,
        )
        if target is None:
            return RegisteredWindowNavigationReadiness(
                wait_reason=NavigationWaitReason.FIELD_TARGET,
            )

        viewport = self._owner._scroll_viewport()
        if not self._target_geometry_is_stable(request, target, viewport):
            return RegisteredWindowNavigationReadiness(
                wait_reason=NavigationWaitReason.LAYOUT,
            )

        if (
            viewport.content_widget is None
            or viewport.viewport_height <= 0
            or viewport.vertical_scroll_bar.maximum() <= 0
        ):
            if self._owner._target_is_visible_for_navigation(
                target,
                viewport,
                is_fallback=is_fallback,
            ):
                return readiness
            return RegisteredWindowNavigationReadiness(
                wait_reason=NavigationWaitReason.LAYOUT,
            )

        if self._owner._target_is_visible_for_navigation(
            target,
            viewport,
            is_fallback=is_fallback,
        ):
            return readiness

        target_scroll = self._owner._navigation_scroll_position(
            target,
            viewport,
            is_fallback=is_fallback,
        )
        if target_scroll > viewport.vertical_scroll_bar.maximum():
            return RegisteredWindowNavigationReadiness(
                wait_reason=NavigationWaitReason.LAYOUT,
            )

        return readiness

    def _target_geometry_is_stable(
        self,
        request: RegisteredWindowNavigationRequest,
        target: ScrollTarget,
        viewport: ScrollViewport,
    ) -> bool:
        widget_top, widget_height, widget_bottom = self._owner._target_visual_bounds(
            target,
            viewport,
        )
        signature = (
            request.field_path,
            id(target.target_widget),
            id(self._owner._target_sizing_widget(target)),
            widget_top,
            widget_height,
            widget_bottom,
            viewport.viewport_height,
            viewport.vertical_scroll_bar.maximum(),
        )
        if signature != self._last_geometry_signature:
            self._last_geometry_signature = signature
            self._stable_geometry_samples = 1
            return False

        self._stable_geometry_samples += 1
        return self._stable_geometry_samples >= self.stable_geometry_sample_count


class ScrollableFormMixin:
    """
    Mixin for widgets that have:
    - self.scroll_area: QScrollArea containing the form
    - self.form_manager: ParameterFormManager with nested_managers

    Provides scroll-to-section functionality.
    Optionally triggers flash animation on the target groupbox.
    """

    # Type hints for attributes that must be provided by the implementing class
    scroll_area: QScrollArea
    form_manager: 'ParameterFormManager'  # Forward reference

    def _scroll_to_section(self, field_name: str, flash: bool = True):
        """Scroll to a specific section or field in the form.

        Supports both:
        - Section names (e.g., 'path_planning_config') - scrolls to groupbox
        - Dotted paths (e.g., 'path_planning_config.well_filter') - scrolls to specific widget

        Args:
            field_name: The field name or dotted path to scroll to
            flash: If True, flash the target groupbox after scrolling
        """
        logger.info(f"🔍 Scrolling to section: {field_name}")

        if self.scroll_area is None:
            logger.warning("Scroll area not initialized; cannot navigate to section")
            return

        target, is_fallback = self._resolve_navigation_scroll_target(field_name)
        if target is None:
            self._resolve_scroll_target(field_name, warn_missing=True)
            return

        viewport = self._scroll_viewport()
        if self._target_is_visible_for_navigation(
            target,
            viewport,
            is_fallback=is_fallback,
        ):
            logger.info(f"✅ Target {field_name} already visible, skipping scroll")
        else:
            target_scroll = self._navigation_scroll_position(
                target,
                viewport,
                is_fallback=is_fallback,
            )
            viewport.vertical_scroll_bar.setValue(target_scroll)
            logger.info(f"✅ Scrolled to {field_name} (target_scroll={target_scroll})")

            # Invalidate flash overlay geometry cache after programmatic scroll
            from pyqt_reactive.animation import WindowFlashOverlay
            WindowFlashOverlay.invalidate_cache_for_widget(self)  # type: ignore[arg-type]

        if flash:
            self._flash_scroll_target(target)

    def _resolve_scroll_target(
        self,
        field_name: str,
        *,
        warn_missing: bool = True,
    ) -> Optional[ScrollTarget]:
        """Resolve a dotted form path to a concrete widget and section path."""
        parts = field_name.split('.')
        current_manager = self.form_manager
        section_parts = []

        for i, part in enumerate(parts[:-1]):
            if part not in current_manager.nested_managers:
                inline_target = self._resolve_inline_dataclass_child_target(
                    field_name=field_name,
                    current_manager=current_manager,
                    section_parts=section_parts,
                    inline_field_name=part,
                    child_field_name=parts[i + 1],
                )
                if inline_target is not None:
                    return inline_target
                if warn_missing:
                    logger.warning(f"❌ Part '{part}' not in nested_managers at depth {i}")
                return None
            current_manager = current_manager.nested_managers[part]
            section_parts.append(part)

        leaf_name = parts[-1]
        section_path = ".".join(section_parts)
        groupbox_widget = None
        target_widget = None

        if leaf_name in current_manager.nested_managers:
            nested_manager = current_manager.nested_managers[leaf_name]
            section_parts.append(leaf_name)
            section_path = ".".join(section_parts)
            groupbox_widget = self.form_manager.form_tree.groupbox_for_prefix(section_path)
            if nested_manager.widgets:
                first_param_name = next(iter(nested_manager.widgets.keys()))
                target_widget = nested_manager.widgets[first_param_name]
        elif leaf_name in current_manager.widgets:
            target_widget = current_manager.widgets[leaf_name]
            inline_owner_target = self._resolve_inline_dataclass_owner_target(
                field_name=field_name,
                current_manager=current_manager,
                section_parts=section_parts,
                inline_field_name=leaf_name,
            )
            if inline_owner_target is not None:
                return inline_owner_target
        else:
            if warn_missing:
                logger.warning(f"❌ Leaf '{leaf_name}' not found in widgets or nested_managers")
            return None

        if target_widget is None:
            if warn_missing:
                logger.warning(f"⚠️ No target widget found for {field_name}")
            return None

        is_field = leaf_name in current_manager.widgets and leaf_name not in current_manager.nested_managers
        return ScrollTarget(
            field_name=field_name,
            leaf_name=leaf_name,
            section_path=section_path,
            target_widget=target_widget,
            groupbox_widget=groupbox_widget,
            current_manager=current_manager,
            is_field=is_field,
        )

    def _resolve_inline_dataclass_owner_target(
        self,
        *,
        field_name: str,
        current_manager: Any,
        section_parts: list[str],
        inline_field_name: str,
    ) -> Optional[ScrollTarget]:
        """Resolve an inline dataclass owner path to its structural container."""
        from pyqt_reactive.widgets.structural_table import (
            resolve_inline_dataclass_structural_target,
        )

        inline_widget = current_manager.widgets.get(inline_field_name)
        if not isinstance(inline_widget, QWidget):
            return None

        inline_prefix = tuple(section_parts + [inline_field_name])
        structural_result = resolve_inline_dataclass_structural_target(
            inline_widget=inline_widget,
            inline_field_path=inline_prefix,
            display_path=field_name,
        )
        if structural_result is None:
            return None

        structural_target = structural_result.target
        return ScrollTarget(
            field_name=field_name,
            leaf_name=structural_result.child_field_name,
            section_path=".".join(inline_prefix),
            target_widget=structural_target.scroll_widget(),
            groupbox_widget=None,
            current_manager=current_manager,
            is_field=False,
            structural_flash_target=structural_target,
        )

    def _resolve_inline_dataclass_child_target(
        self,
        *,
        field_name: str,
        current_manager: Any,
        section_parts: list[str],
        inline_field_name: str,
        child_field_name: str,
    ) -> Optional[ScrollTarget]:
        """Resolve a child field rendered inside an inline dataclass widget."""
        from pyqt_reactive.protocols import (
            ChildFieldNavigationTargetProvider,
        )
        from pyqt_reactive.widgets.structural_table import (
            resolve_inline_dataclass_structural_target,
        )
        from pyqt_reactive.widgets.shared.clickable_help_components import (
            InlineDataclassGroupBox,
        )

        inline_widget = current_manager.widgets.get(inline_field_name)
        if not isinstance(inline_widget, InlineDataclassGroupBox):
            return None

        inline_prefix = tuple(section_parts + [inline_field_name])
        structural_result = resolve_inline_dataclass_structural_target(
            inline_widget=inline_widget,
            inline_field_path=inline_prefix,
            display_path=field_name,
            owner_child_field_name=child_field_name,
        )
        if structural_result is not None:
            structural_target = structural_result.target
            return ScrollTarget(
                field_name=field_name,
                leaf_name=structural_result.child_field_name,
                section_path=".".join(section_parts + [inline_field_name]),
                target_widget=structural_target.scroll_widget(),
                groupbox_widget=None,
                current_manager=current_manager,
                is_field=False,
                structural_flash_target=structural_target,
            )

        target_widget: QWidget
        if isinstance(inline_widget, ChildFieldNavigationTargetProvider):
            child_widget = inline_widget.child_field_navigation_target(child_field_name)
            if not isinstance(child_widget, QWidget):
                return None
            target_widget = child_widget
        else:
            target_widget = inline_widget

        section_path = ".".join(section_parts + [inline_field_name])
        return ScrollTarget(
            field_name=field_name,
            leaf_name=child_field_name,
            section_path=section_path,
            target_widget=target_widget,
            groupbox_widget=None,
            current_manager=current_manager,
            is_field=False,
        )

    def _resolve_nearest_ancestor_scroll_target(self, field_name: str) -> Optional[ScrollTarget]:
        """Resolve the nearest visible ancestor for a missing deep field path."""
        parts = tuple(part for part in field_name.split(".") if part)
        if len(parts) <= 1:
            return None

        for prefix_length in range(len(parts) - 1, 0, -1):
            ancestor_path = ".".join(parts[:prefix_length])
            target = self._resolve_scroll_target(
                ancestor_path,
                warn_missing=False,
            )
            if target is not None:
                return target

        return None

    def _resolve_navigation_scroll_target(
        self,
        field_name: str,
    ) -> tuple[ScrollTarget | None, bool]:
        """Resolve a navigation target and whether it is an ancestor fallback."""

        target = self._resolve_scroll_target(field_name, warn_missing=False)
        if target is not None:
            return target, False
        return self._resolve_nearest_ancestor_scroll_target(field_name), True

    def _scroll_viewport(self) -> ScrollViewport:
        """Capture scroll-area geometry once for a navigation operation."""
        content_widget = self.scroll_area.widget()
        v_scroll_bar = self.scroll_area.verticalScrollBar()
        viewport_height = self.scroll_area.viewport().height()
        viewport_top = v_scroll_bar.value()
        return ScrollViewport(
            content_widget=content_widget,
            viewport_height=viewport_height,
            viewport_top=viewport_top,
            viewport_bottom=viewport_top + viewport_height,
            vertical_scroll_bar=v_scroll_bar,
        )

    def _target_sizing_widget(self, target: ScrollTarget) -> QWidget:
        """Use section groupboxes for section navigation and leaf widgets for fields."""
        if target.groupbox_widget is not None and not target.is_field:
            return target.groupbox_widget
        return target.target_widget

    def _target_bounds(self, widget: QWidget, viewport: ScrollViewport) -> tuple[int, int, int]:
        widget_pos = widget.mapTo(viewport.content_widget, widget.rect().topLeft())
        widget_height = widget.height()
        widget_top = widget_pos.y()
        return widget_top, widget_height, widget_top + widget_height

    def _target_visual_bounds(
        self,
        target: ScrollTarget,
        viewport: ScrollViewport,
    ) -> tuple[int, int, int]:
        if target.structural_flash_target is not None:
            rect = target.structural_flash_target.scroll_rect_in(viewport.content_widget)
            if rect is not None:
                return rect.y(), rect.height(), rect.y() + rect.height()
        return self._target_bounds(self._target_sizing_widget(target), viewport)

    def _target_is_fully_visible(self, target: ScrollTarget, viewport: ScrollViewport) -> bool:
        widget_top, _, widget_bottom = self._target_visual_bounds(target, viewport)
        return widget_top >= viewport.viewport_top and widget_bottom <= viewport.viewport_bottom

    def _target_is_visible_for_navigation(
        self,
        target: ScrollTarget,
        viewport: ScrollViewport,
        *,
        is_fallback: bool,
    ) -> bool:
        """Return whether navigation already has enough target context in view.

        Exact targets must be fully visible. A nearest-ancestor fallback is only
        a contextual approximation for a structural leaf that no longer exists,
        so any visible portion of that ancestor is sufficient and must not
        displace the user's current viewport.
        """

        if not is_fallback:
            return self._target_is_fully_visible(target, viewport)
        widget_top, widget_height, widget_bottom = self._target_visual_bounds(
            target,
            viewport,
        )
        return (
            widget_height > 0
            and widget_bottom > viewport.viewport_top
            and widget_top < viewport.viewport_bottom
        )

    def _navigation_scroll_position(
        self,
        target: ScrollTarget,
        viewport: ScrollViewport,
        *,
        is_fallback: bool,
    ) -> int:
        """Return the navigation position for an exact or contextual target."""

        if not is_fallback:
            return self._target_scroll_position(target, viewport)

        widget_top, widget_height, widget_bottom = self._target_visual_bounds(
            target,
            viewport,
        )
        if widget_height >= viewport.viewport_height:
            if widget_bottom <= viewport.viewport_top:
                return max(0, widget_bottom - 1)
            if widget_top >= viewport.viewport_bottom:
                return max(0, widget_top - viewport.viewport_height + 1)
            return viewport.viewport_top
        if widget_top < viewport.viewport_top:
            return max(0, widget_top)
        if widget_bottom > viewport.viewport_bottom:
            return max(0, widget_bottom - viewport.viewport_height)
        return viewport.viewport_top

    def _target_scroll_position(self, target: ScrollTarget, viewport: ScrollViewport) -> int:
        if target.is_field:
            return self._field_scroll_position(target, viewport)
        return self._section_scroll_position(target, viewport)

    def _field_scroll_position(self, target: ScrollTarget, viewport: ScrollViewport) -> int:
        field_center = self._widget_center(target.target_widget, viewport)
        return max(0, field_center - viewport.viewport_height // 2)

    def _section_scroll_position(self, target: ScrollTarget, viewport: ScrollViewport) -> int:
        widget_top, widget_height, _ = self._target_visual_bounds(target, viewport)

        if widget_height >= viewport.viewport_height:
            logger.debug(
                f"📜 SCROLL: {target.field_name} taller than viewport, top-aligning: "
                f"widget_height={widget_height}, viewport_height={viewport.viewport_height}"
            )
            return widget_top

        widget_center = widget_top + widget_height // 2
        target_scroll = max(0, widget_center - viewport.viewport_height // 2)
        logger.debug(
            f"📜 SCROLL: {target.field_name} centering: widget_top={widget_top}, "
            f"widget_height={widget_height}, widget_center={widget_center}, "
            f"viewport_height={viewport.viewport_height}, target_scroll={target_scroll}"
        )
        return target_scroll

    def _widget_center(self, widget: QWidget, viewport: ScrollViewport) -> int:
        widget_top, widget_height, _ = self._target_bounds(widget, viewport)
        return widget_top + widget_height // 2

    def _flash_scroll_target(self, target: ScrollTarget) -> None:
        """Flash the resolved target locally after navigation."""
        if target.structural_flash_target is not None:
            target_key = target.field_name
            target.structural_flash_target.register_flash(self.form_manager, target_key)
            logger.info(
                f"⚡ FLASH_DEBUG: Calling queue_flash_local({target_key}) "
                f"on form_manager scope_id={self.form_manager.scope_id}"
            )
            self.form_manager.queue_flash_local(target_key)
            return
        if target.is_field:
            self.form_manager._queue_leaf_flash_for_path(target.field_name)
        elif target.section_path and target.field_name != target.section_path:
            self.form_manager._queue_leaf_flash_for_path(target.field_name)
        elif target.section_path:
            logger.info(
                f"⚡ FLASH_DEBUG: Calling queue_flash_local({target.section_path}) "
                f"on form_manager scope_id={self.form_manager.scope_id}"
            )
            self.form_manager.queue_flash_local(target.section_path)
        logger.debug(f"⚡ Flashed for {target.field_name} (local)")

    def select_and_scroll_to_field(self, field_path: str) -> None:
        """Public API for WindowManager navigation protocol.

        Scrolls to and highlights the specified field.
        This method name matches the protocol expected by WindowManager.focus_and_navigate().
        """
        self._scroll_to_section(field_path, flash=True)

    def window_navigation_driver(self) -> WindowNavigationDriver:
        """Return explicit form-field navigation behavior for WindowManager."""
        return ScrollableFormWindowNavigationDriver(self)
