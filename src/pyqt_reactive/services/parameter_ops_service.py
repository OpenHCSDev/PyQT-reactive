"""Refresh inherited previews; admitted mutation events own writes and resets."""

from __future__ import annotations


import logging

from formbridge.core.performance_monitor import get_monitor, timer


logger = logging.getLogger(__name__)


class ParameterOpsService:
    """Refresh inherited previews for already materialized form trees."""

    def refresh_single_placeholder(self, manager, field_name: str) -> None:
        """Refresh placeholder for a single field in a manager.

        WidgetService admits inherited fields and paints their canonical read;
        literal None and absence do not become inheritance.

        Args:
            manager: The manager containing the field
            field_name: Name of the field to refresh
        """
        logger.debug(f"🔬 RESET_TRACE: refresh_single_placeholder: {manager.field_id}.{field_name}")

        # Check if field exists in this manager's widgets
        if field_name not in manager.widgets:
            logger.debug(f"🔬 RESET_TRACE: {field_name} not in widgets, skipping")
            return

        from pyqt_reactive.forms.widget_strategies import PyQt6WidgetEnhancer

        widget = manager.widgets[field_name]
        if not PyQt6WidgetEnhancer.supports_placeholder(widget):
            return

        manager._widget_service.show_resolved_value_as_placeholder(widget, field_name, manager)

    def refresh_with_live_context(self, manager, defer: bool = False) -> None:
        """Refresh placeholders using live values from tree registry.

        Args:
            manager: ParameterFormManager instance to refresh
            defer: If True, defer refresh through the manager-owned QObject
                lifecycle so async widget creation can complete safely.
        """
        logger.debug(f"🔍 REFRESH: {manager.field_id} (id={id(manager)}) refreshing placeholders, defer={defer}")

        if defer:
            manager.schedule_lifecycle_callback(
                0,
                lambda: self._deferred_refresh_with_live_context(manager),
            )
        else:
            self._refresh_form_tree(manager)

    def _deferred_refresh_with_live_context(self, manager) -> None:
        """Run a deferred refresh while its manager QObject is still alive."""
        self._refresh_form_tree(manager)

    def _refresh_form_tree(self, manager) -> None:
        """Refresh one manager subtree without overlapping recursive traversals."""
        self._refresh_placeholder_tree(manager)
        manager._enabled_field_styling_service.refresh_enabled_styling(manager)
        self._refresh_root_flash_registrations(manager)

    def _refresh_placeholder_tree(self, manager) -> None:
        """Refresh placeholder values exactly once for each manager in a subtree."""
        self.refresh_all_placeholders(manager)
        manager._apply_to_nested_managers(
            lambda _name, nested_manager: self._refresh_placeholder_tree(nested_manager)
        )

    def _refresh_root_flash_registrations(self, manager) -> None:
        """Replay flash registrations after a root form refreshes live placeholders."""
        if manager._parent_manager is not None:
            return
        manager.reregister_flash_elements()

    def refresh_all_placeholders(self, manager) -> None:
        """Refresh previews through WidgetService's inheritance admission."""
        with timer(f"_refresh_all_placeholders ({manager.field_id})", threshold_ms=5.0):
            if not manager.object_instance:
                logger.debug(f"[PLACEHOLDER] {manager.field_id}: No obj_type, skipping")
                return

            from pyqt_reactive.forms.widget_strategies import PyQt6WidgetEnhancer
            logger.debug(f"[PLACEHOLDER] {manager.field_id}: Refreshing placeholders via ObjectState")

            monitor = get_monitor("Placeholder resolution per field")

            for param_name, widget in manager.widgets.items():
                # Guard: Skip deleted widgets (can happen if window closed during async build)
                try:
                    # Access any attribute to check if widget is still valid
                    _ = widget.objectName()
                except RuntimeError:
                    logger.debug(f"[PLACEHOLDER] {manager.field_id}: Widget {param_name} was deleted, skipping")
                    continue

                if not PyQt6WidgetEnhancer.supports_placeholder(widget):
                    continue

                with monitor.measure():
                    manager._widget_service.show_resolved_value_as_placeholder(
                        widget, param_name, manager
                    )
