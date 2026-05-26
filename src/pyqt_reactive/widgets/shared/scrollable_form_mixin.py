"""
Mixin for widgets that manage a ParameterFormManager with a scroll area.

Provides common functionality for scrolling to sections in the form.
Used by ConfigWindow and StepParameterEditorWidget.
"""
import logging
from dataclasses import dataclass
from typing import Any, Optional

from PyQt6.QtWidgets import QScrollArea, QWidget

from pyqt_reactive.services.window_navigation import FieldNavigableWindow, FormManagedWindow

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


@dataclass(frozen=True)
class ScrollViewport:
    """Snapshot of scroll-area geometry used to compute navigation."""

    content_widget: QWidget
    viewport_height: int
    viewport_top: int
    viewport_bottom: int
    vertical_scroll_bar: Any


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

        target = self._resolve_scroll_target(field_name)
        if target is None:
            return

        viewport = self._scroll_viewport()
        if self._target_is_fully_visible(target, viewport):
            logger.info(f"✅ Target {field_name} already visible, skipping scroll")
        else:
            target_scroll = self._target_scroll_position(target, viewport)
            viewport.vertical_scroll_bar.setValue(target_scroll)
            logger.info(f"✅ Scrolled to {field_name} (target_scroll={target_scroll})")

            # Invalidate flash overlay geometry cache after programmatic scroll
            from pyqt_reactive.animation import WindowFlashOverlay
            WindowFlashOverlay.invalidate_cache_for_widget(self)  # type: ignore[arg-type]

        if flash:
            self._flash_scroll_target(target)

    def _resolve_scroll_target(self, field_name: str) -> Optional[ScrollTarget]:
        """Resolve a dotted form path to a concrete widget and section path."""
        parts = field_name.split('.')
        current_manager = self.form_manager
        section_parts = []

        for i, part in enumerate(parts[:-1]):
            if part not in current_manager.nested_managers:
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
        else:
            logger.warning(f"❌ Leaf '{leaf_name}' not found in widgets or nested_managers")
            return None

        if target_widget is None:
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

    def _target_is_fully_visible(self, target: ScrollTarget, viewport: ScrollViewport) -> bool:
        sizing_widget = self._target_sizing_widget(target)
        widget_top, _, widget_bottom = self._target_bounds(sizing_widget, viewport)
        return widget_top >= viewport.viewport_top and widget_bottom <= viewport.viewport_bottom

    def _target_scroll_position(self, target: ScrollTarget, viewport: ScrollViewport) -> int:
        if target.is_field:
            return self._field_scroll_position(target, viewport)
        return self._section_scroll_position(target, viewport)

    def _field_scroll_position(self, target: ScrollTarget, viewport: ScrollViewport) -> int:
        groupbox_for_field = target.groupbox_widget or (
            self.form_manager.form_tree.groupbox_for_prefix(target.section_path)
            if target.section_path
            else None
        )
        if groupbox_for_field:
            gb_top, gb_height, _ = self._target_bounds(groupbox_for_field, viewport)
            if gb_height <= viewport.viewport_height:
                gb_center = gb_top + gb_height // 2
                target_scroll = max(0, gb_center - viewport.viewport_height // 2)
                logger.debug(
                    f"📜 SCROLL: Field {target.field_name} - groupbox fits, centering groupbox: "
                    f"gb_height={gb_height}, viewport_height={viewport.viewport_height}"
                )
                return target_scroll

            field_center = self._widget_center(target.target_widget, viewport)
            logger.debug(f"📜 SCROLL: Field {target.field_name} - groupbox too tall, centering field")
            return max(0, field_center - viewport.viewport_height // 2)

        field_center = self._widget_center(target.target_widget, viewport)
        return max(0, field_center - viewport.viewport_height // 2)

    def _section_scroll_position(self, target: ScrollTarget, viewport: ScrollViewport) -> int:
        sizing_widget = self._target_sizing_widget(target)
        widget_top, widget_height, _ = self._target_bounds(sizing_widget, viewport)

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
        if target.is_field:
            self._queue_leaf_flash_for_navigation(target.section_path, target.leaf_name, target.target_widget)
        elif target.section_path:
            logger.info(
                f"⚡ FLASH_DEBUG: Calling queue_flash_local({target.section_path}) "
                f"on form_manager scope_id={getattr(self.form_manager, 'scope_id', 'NONE')}"
            )
            self.form_manager.queue_flash_local(target.section_path)
            self.form_manager.queue_flash_local(f"tree::{target.section_path}")
        logger.debug(f"⚡ Flashed for {target.field_name} (local)")

    def _queue_leaf_flash_for_navigation(self, section_path: str, leaf_name: str, leaf_widget) -> None:
        """Queue a leaf flash for navigation to a specific field.

        Uses INVERSE masking: flash the groupbox + all siblings, mask the leaf widget + its label.
        This highlights "all fields that inherited the change" while keeping
        the actual changed widget visible.

        For ROOT fields (no section_path), flash the entire form area.
        """
        from pyqt_reactive.animation import WindowFlashOverlay
        from pyqt_reactive.animation.flash_mixin import _GlobalFlashCoordinator

        logger.debug(f"🔍 QUEUE_LEAF_NAV_START section_path='{section_path}' leaf_name='{leaf_name}' leaf_widget={type(leaf_widget).__name__ if leaf_widget else None}")

        # Get the overlay and check what's registered
        window = self.window()
        overlay = WindowFlashOverlay._overlays.get(id(window)) if window else None

        if not section_path:
            # Root field case - use the same approach as editing (line 1146-1209 in parameter_form_manager.py)
            logger.debug(f"🔍 QUEUE_LEAF_NAV_ROOT section='{leaf_name}'")

            # Get the groupbox (same as editing: parent of form_manager)
            groupbox = self.form_manager.parent()
            # Get the leaf widget (same as editing: from widgets dict)
            actual_leaf_widget = self.form_manager.widgets.get(leaf_name)
            # Get the label widget (for proper masking)
            label_widget = self.form_manager.labels.get(leaf_name)

            logger.debug(f"🔍 QUEUE_LEAF_NAV: groupbox={type(groupbox).__name__ if groupbox else None}")
            logger.debug(f"🔍 QUEUE_LEAF_NAV: leaf_widget={type(actual_leaf_widget).__name__ if actual_leaf_widget else None}")
            logger.debug(f"🔍 QUEUE_LEAF_NAV: label_widget={type(label_widget).__name__ if label_widget else None}")

            if groupbox and actual_leaf_widget:
                # Register with groupbox, leaf_widget, AND label_widget
                leaf_flash_key = f"param_{leaf_name}"
                logger.debug(f"🔍 QUEUE_LEAF_NAV: register_flash_leaf key='{leaf_flash_key}'")
                logger.debug(f"🔍 QUEUE_LEAF_NAV: groupbox geometry={groupbox.geometry()}")
                logger.debug(f"🔍 QUEUE_LEAF_NAV: leaf_widget geometry={actual_leaf_widget.geometry()}")
                if label_widget:
                    logger.debug(f"🔍 QUEUE_LEAF_NAV: label_widget geometry={label_widget.geometry()}")
                # Pass label_widget instead of None for proper masking
                self.form_manager.register_flash_leaf(leaf_flash_key, groupbox, actual_leaf_widget, label_widget=label_widget)

            # Process pending registrations
            _GlobalFlashCoordinator.get()._process_pending_registrations()

            # Queue the flash
            leaf_flash_key = f"param_{leaf_name}"
            self.form_manager.queue_flash_local(leaf_flash_key)
            logger.debug(f"🔍 QUEUE_LEAF_NAV_QUEUED key='{leaf_flash_key}'")
            return

        # Nested field case
        leaf_flash_key = f"{section_path}.{leaf_name}"
        logger.debug(f"🔍 QUEUE_LEAF_NAV_NESTED section='{section_path}' leaf='{leaf_name}' key='{leaf_flash_key}'")

        # Get widgets for nested field - same approach as editing
        groupbox = self.form_manager.form_tree.groupbox_for_prefix(section_path)
        nested_manager = self.form_manager.form_tree.nested_manager_for_prefix(section_path)
        leaf_widget = nested_manager.widgets.get(leaf_name) if nested_manager else None
        label_widget = nested_manager.labels.get(leaf_name) if nested_manager else None

        logger.debug(f"🔍 QUEUE_LEAF_NAV_NESTED groupbox={type(groupbox).__name__ if groupbox else None}")
        logger.debug(f"🔍 QUEUE_LEAF_NAV_NESTED leaf_widget={type(leaf_widget).__name__ if leaf_widget else None}")
        logger.debug(f"🔍 QUEUE_LEAF_NAV_NESTED label_widget={type(label_widget).__name__ if label_widget else None}")

        if groupbox and leaf_widget:
            # Call SAME method as editing - register_flash_leaf with label_widget
            logger.debug(f"🔍 QUEUE_LEAF_NAV_NESTED: Calling register_flash_leaf")
            self.form_manager.register_flash_leaf(leaf_flash_key, groupbox, leaf_widget, label_widget=label_widget)

        # Process pending registrations
        _GlobalFlashCoordinator.get()._process_pending_registrations()

        # Queue the flash
        self.form_manager.queue_flash_local(leaf_flash_key)
        self.form_manager.queue_flash_local(f"tree::{section_path}")
        logger.debug(f"🔍 QUEUE_LEAF_NAV_NESTED_QUEUED leaf='{leaf_flash_key}' tree='tree::{section_path}'")

    def select_and_scroll_to_field(self, field_path: str) -> None:
        """Public API for WindowManager navigation protocol.

        Scrolls to and highlights the specified field.
        This method name matches the protocol expected by WindowManager.focus_and_navigate().
        """
        self._scroll_to_section(field_path, flash=True)


FieldNavigableWindow.register(ScrollableFormMixin)
FormManagedWindow.register(ScrollableFormMixin)
