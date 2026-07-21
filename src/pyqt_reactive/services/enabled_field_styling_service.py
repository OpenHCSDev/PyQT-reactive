"""Enabled Field Styling Service - Visual styling for enabled/disabled states."""

import logging
from typing import Any
from weakref import WeakKeyDictionary

from objectstate.time_travel_profile import TimeTravelProfiler
from PyQt6 import sip
from PyQt6.QtWidgets import QCheckBox, QGraphicsOpacityEffect, QLabel

from pyqt_reactive.protocols import PlaceholderStateTrackable

logger = logging.getLogger(__name__)


class EnabledFieldStylingService:
    """
    Service for applying visual styling based on enabled field state.

    Stateless service that encapsulates all enabled field styling operations.
    """

    def __init__(self):
        """Initialize enabled field styling service (stateless - imports dependencies)."""
        from pyqt_reactive.forms.widget_operations import WidgetOperations
        self.widget_ops = WidgetOperations
        self._last_enabled_values: WeakKeyDictionary[Any, bool] = WeakKeyDictionary()
        self._direct_widgets_by_manager: WeakKeyDictionary[Any, list] = WeakKeyDictionary()
        self._value_widgets_by_container: WeakKeyDictionary[Any, list] = WeakKeyDictionary()
        self._dimmed_property_name = "enabled_field_dimmed"
        self._dimmed_opacity = 0.4

    def invalidate_widget_cache(self, manager) -> None:
        """Invalidate cached widget discovery after a form's widget tree changes."""
        self._last_enabled_values.pop(manager, None)
        self._direct_widgets_by_manager.pop(manager, None)
        group_box = manager.form_tree.owning_groupbox(manager)
        if group_box is not None:
            self._value_widgets_by_container.pop(group_box, None)
    
    def apply_initial_enabled_styling(self, manager) -> None:
        """
        Apply initial enabled field styling based on resolved value from widget.

        This is called once after all widgets are created to ensure initial styling matches the enabled state.

        CRITICAL: This should NOT be called for optional dataclass nested managers when instance is None.
        The None state dimming is handled by the optional dataclass checkbox handler.

        Args:
            manager: ParameterFormManager instance
        """
        # Check if this is a nested manager inside an optional dataclass with None instance
        if self._should_skip_optional_dataclass_styling(manager, "INITIAL ENABLED STYLING"):
            return

        self._last_enabled_values.pop(manager, None)
        logger.debug(
            "[INITIAL_STYLING] field_id=%s, cleared cache to force initial styling",
            manager.field_id,
        )

        # Get the enabled widget
        enabled_widget = manager.widgets.get('enabled')
        if not enabled_widget:
            logger.debug(f"[INITIAL_STYLING] field_id={manager.field_id}, no enabled widget found")
            return
        if sip.isdeleted(enabled_widget):
            logger.debug(f"[INITIAL_STYLING] field_id={manager.field_id}, enabled widget was deleted")
            return

        # Get resolved value from checkbox
        if isinstance(enabled_widget, QCheckBox):
            resolved_value = enabled_widget.isChecked()
            logger.debug(f"[INITIAL_STYLING] field_id={manager.field_id}, resolved_value={resolved_value} (from checkbox)")
        else:
            # Fallback to parameter value
            resolved_value = manager.parameters.get('enabled')
            if resolved_value is None:
                resolved_value = True  # Default to enabled if we can't resolve
            logger.debug(f"[INITIAL_STYLING] field_id={manager.field_id}, resolved_value={resolved_value} (from parameter)")

        # Call the enabled handler with the resolved value
        self.on_enabled_field_changed(manager, 'enabled', resolved_value)
    
    def refresh_enabled_styling(self, manager) -> None:
        """
        Refresh enabled styling for a form and all nested forms.
        
        This should be called when context changes that might affect inherited enabled values.
        Similar to placeholder refresh, but for enabled field styling.
        
        CRITICAL: Skip optional dataclass nested managers when instance is None.
        
        Args:
            manager: ParameterFormManager instance
        """
        # Check if this is a nested manager inside an optional dataclass with None instance
        if self._should_skip_optional_dataclass_styling(manager, "REFRESH ENABLED STYLING"):
            return
        
        # Refresh this form's enabled styling if it has an enabled field
        if 'enabled' in manager.parameters:
            # Get the enabled widget to read the CURRENT resolved value
            enabled_widget = manager.widgets.get('enabled')
            if enabled_widget and sip.isdeleted(enabled_widget):
                logger.debug(f"[REFRESH ENABLED STYLING] field_id={manager.field_id}, enabled widget was deleted")
                return
            if enabled_widget and isinstance(enabled_widget, QCheckBox):
                # Use the checkbox's current state (which reflects resolved placeholder)
                resolved_value = enabled_widget.isChecked()
            else:
                # Fallback to parameter value
                resolved_value = manager.parameters.get('enabled')
                if resolved_value is None:
                    resolved_value = True
            
            # Apply styling with the resolved value
            self.on_enabled_field_changed(manager, 'enabled', resolved_value)
        
        # Recursively refresh all nested forms' enabled styling
        for nested_manager in manager.nested_managers.values():
            self.refresh_enabled_styling(nested_manager)
    
    def on_enabled_field_changed(self, manager, param_name: str, value: Any) -> None:
        """
        Apply visual styling when 'enabled' parameter changes.

        This handler is connected for ANY form that has an 'enabled' parameter.
        When enabled resolves to False, apply visual dimming WITHOUT blocking input.

        PERFORMANCE: Early exit if value unchanged to avoid redundant styling.

        Args:
            manager: ParameterFormManager instance
            param_name: Parameter name (should be 'enabled')
            value: New value (True/False/None)
        """
        if param_name != 'enabled':
            return

        logger.debug(f"[ENABLED_HANDLER] >>> CALLED for field_id={manager.field_id}, value={value}")

        # Resolve lazy value
        if value is None:
            # Lazy field - get the resolved value from ObjectState
            # This ensures we get the actual resolved value, not the raw parameter
            full_path = f"{manager.field_id}.enabled" if manager.field_id else "enabled"
            resolved_value = manager.state.get_resolved_value(full_path)
            if resolved_value is None:
                # True is the default for enabled fields
                resolved_value = True
        else:
            resolved_value = value

        # PERFORMANCE: Skip if value hasn't changed
        if (
            manager in self._last_enabled_values
            and self._last_enabled_values[manager] == resolved_value
        ):
            logger.debug(f"[ENABLED_HANDLER] field_id={manager.field_id}, SKIP (value unchanged: {resolved_value})")
            return
        self._last_enabled_values[manager] = resolved_value

        logger.debug(f"[ENABLED_HANDLER] field_id={manager.field_id}, resolved_value={resolved_value}")

        # Get direct widgets (excluding nested managers) - CACHED
        direct_widgets = self._get_direct_widgets(manager)
        logger.debug(f"[ENABLED_HANDLER] field_id={manager.field_id}, direct_widgets count={len(direct_widgets)}")

        # Check if this is a nested config
        is_nested_config = manager._parent_manager is not None and any(
            nested_manager == manager for nested_manager in manager._parent_manager.nested_managers.values()
        )

        if is_nested_config:
            self._apply_nested_config_styling(manager, resolved_value)
        else:
            self._apply_top_level_styling(manager, resolved_value, direct_widgets)
    
    def _should_skip_optional_dataclass_styling(self, manager, log_prefix: str) -> bool:
        """
        Check if this is a nested manager inside an optional dataclass with None instance.
        
        Args:
            manager: ParameterFormManager instance
            log_prefix: Prefix for log messages
        
        Returns:
            True if styling should be skipped, False otherwise
        """
        if manager._parent_manager is not None:
            for param_name, nested_manager in manager._parent_manager.nested_managers.items():
                if nested_manager is manager:
                    param_type = manager._parent_manager.parameter_types.get(param_name)
                    if param_type:
                        from pyqt_reactive.forms.parameter_type_utils import ParameterTypeUtils
                        if ParameterTypeUtils.is_optional_dataclass(param_type):
                            instance = manager._parent_manager.parameters.get(param_name)
                            logger.debug(f"[{log_prefix}] field_id={manager.field_id}, optional dataclass check: param_name={param_name}, instance={instance}, is_none={instance is None}")
                            if instance is None:
                                logger.debug(f"[{log_prefix}] field_id={manager.field_id}, skipping (optional dataclass instance is None)")
                                return True
                    break
        return False
    
    def _get_direct_widgets(self, manager):
        """
        Get widgets that belong to this form, excluding nested ParameterFormManager widgets.

        PERFORMANCE: Cached per manager instance - widget list doesn't change after form creation.

        Args:
            manager: ParameterFormManager instance

        Returns:
            List of widgets belonging to this form
        """
        if manager in self._direct_widgets_by_manager:
            return self._direct_widgets_by_manager[manager]

        direct_widgets = []
        all_widgets = self.widget_ops.get_all_value_widgets(manager)
        logger.debug(f"[GET_DIRECT_WIDGETS] field_id={manager.field_id}, total widgets found: {len(all_widgets)}, nested_managers: {list(manager.nested_managers.keys())}")

        for widget in all_widgets:
            if sip.isdeleted(widget):
                continue
            widget_name = f"{widget.__class__.__name__}({widget.objectName() or 'no-name'})"
            object_name = widget.objectName()

            # Check if widget belongs to a nested manager
            belongs_to_nested = False
            for nested_name, nested_manager in manager.nested_managers.items():
                nested_field_id = nested_manager.field_id
                if object_name and object_name.startswith(nested_field_id + '_'):
                    belongs_to_nested = True
                    logger.debug(f"[GET_DIRECT_WIDGETS] ❌ EXCLUDE {widget_name} - belongs to nested manager {nested_field_id}")
                    break

            if not belongs_to_nested:
                direct_widgets.append(widget)
                logger.debug(f"[GET_DIRECT_WIDGETS] ✅ INCLUDE {widget_name}")

        logger.debug(f"[GET_DIRECT_WIDGETS] field_id={manager.field_id}, returning {len(direct_widgets)} direct widgets")

        self._direct_widgets_by_manager[manager] = direct_widgets
        return direct_widgets
    
    def _is_any_ancestor_disabled(self, manager) -> bool:
        """
        Check if any ancestor form has enabled=False.

        This is used to determine if a nested config should remain dimmed
        even if its own enabled field is True.

        Args:
            manager: ParameterFormManager instance

        Returns:
            True if any ancestor has enabled=False, False otherwise
        """
        current = manager._parent_manager
        while current is not None:
            if 'enabled' in current.parameters:
                enabled_widget = current.widgets.get('enabled')
                if enabled_widget and sip.isdeleted(enabled_widget):
                    return False
                if enabled_widget and isinstance(enabled_widget, QCheckBox):
                    if not enabled_widget.isChecked():
                        return True
            current = current._parent_manager
        return False

    def _apply_nested_config_styling(self, manager, resolved_value: bool) -> None:
        """
        Apply styling to a nested config (inside GroupBox).

        Args:
            manager: ParameterFormManager instance
            resolved_value: Resolved enabled value (True/False)
        """
        group_box = manager.form_tree.owning_groupbox(manager)
        if not group_box:
            return
        if sip.isdeleted(group_box):
            return

        logger.debug(f"[ENABLED HANDLER] field_id={manager.field_id}, applying to GroupBox container")

        # Check if ANY ancestor has enabled=False
        ancestor_is_disabled = self._is_any_ancestor_disabled(manager)
        logger.debug(f"[ENABLED HANDLER] field_id={manager.field_id}, ancestor_is_disabled={ancestor_is_disabled}")

        should_dim = ancestor_is_disabled or not resolved_value
        widgets = self._get_value_widgets(group_box)
        with TimeTravelProfiler.phase(
            "pyqt.enabled.apply_nested",
            manager_field_id=manager.field_id,
            widgets=len(widgets),
            dimmed=should_dim,
        ):
            changed = self._set_widgets_dimmed(
                widgets,
                should_dim,
                preserve_placeholder_paint=False,
            )

        if changed:
            group_box.update()

    def _apply_top_level_styling(self, manager, resolved_value: bool, direct_widgets: list) -> None:
        """
        Apply styling to a top-level form (step, function).

        Args:
            manager: ParameterFormManager instance
            resolved_value: Resolved enabled value (True/False)
            direct_widgets: List of direct widgets (excluding nested managers)
        """
        if resolved_value:
            # Enabled=True: Remove dimming from direct widgets
            logger.debug(f"[ENABLED HANDLER] field_id={manager.field_id}, removing dimming (enabled=True)")
            self._set_widgets_dimmed(direct_widgets, False)

            # Trigger refresh of all nested configs' enabled styling
            logger.debug(f"[ENABLED HANDLER] Refreshing nested configs' enabled styling")
            for nested_manager in manager.nested_managers.values():
                self.refresh_enabled_styling(nested_manager)
        else:
            # Enabled=False: Apply dimming to direct widgets + ALL nested configs
            logger.debug(f"[ENABLED HANDLER] field_id={manager.field_id}, applying dimming (enabled=False)")
            self._set_widgets_dimmed(
                direct_widgets,
                True,
                skip_labels=True,
            )

            # Also dim all nested configs
            logger.debug(f"[ENABLED HANDLER] Dimming nested configs, found {len(manager.nested_managers)} nested managers")
            logger.debug(f"[ENABLED HANDLER] Available widget keys: {list(manager.widgets.keys())}")
            for param_name, nested_manager in manager.nested_managers.items():
                group_box = manager.widgets.get(param_name)
                logger.debug(f"[ENABLED HANDLER] Checking nested config {param_name}, group_box={group_box.__class__.__name__ if group_box else 'None'}")
                if not group_box:
                    logger.debug(f"[ENABLED HANDLER] ⚠️ No group_box found for nested config {param_name}, trying nested_manager.field_id={nested_manager.field_id}")
                    # Try using the nested manager's field_id instead
                    group_box = manager.widgets.get(nested_manager.field_id)
                    if not group_box:
                        logger.debug(f"[ENABLED HANDLER] ⚠️ Still no group_box found, skipping")
                        continue
                if sip.isdeleted(group_box):
                    continue

                widgets_to_dim = self._get_value_widgets(group_box)
                logger.debug(f"[ENABLED HANDLER] Applying dimming to nested config {param_name}, found {len(widgets_to_dim)} widgets")
                changed = self._set_widgets_dimmed(
                    widgets_to_dim,
                    True,
                    preserve_placeholder_paint=False,
                )

                if changed:
                    group_box.update()

    def _get_value_widgets(self, container) -> list:
        """Return cached nominal value widgets for a stable form container."""
        if container in self._value_widgets_by_container:
            return self._value_widgets_by_container[container]
        widgets = self.widget_ops.get_all_value_widgets(container)
        self._value_widgets_by_container[container] = widgets
        return widgets

    def _set_widget_dimmed(
        self,
        widget,
        dimmed: bool,
        *,
        preserve_placeholder_paint: bool = True,
    ) -> bool:
        """Apply this service's dimming effect only when the widget state changes."""
        if sip.isdeleted(widget):
            return False

        if (
            dimmed
            and preserve_placeholder_paint
            and isinstance(widget, PlaceholderStateTrackable)
            and widget.has_placeholder_state()
        ):
            dimmed = False

        current = widget.property(self._dimmed_property_name) is True
        if current == dimmed:
            return False

        widget.setProperty(self._dimmed_property_name, dimmed)
        if dimmed:
            effect = QGraphicsOpacityEffect()
            effect.setOpacity(self._dimmed_opacity)
            widget.setGraphicsEffect(effect)
        else:
            widget.setGraphicsEffect(None)
        widget.update()
        return True

    def _set_widgets_dimmed(
        self,
        widgets: list,
        dimmed: bool,
        *,
        skip_labels: bool = False,
        preserve_placeholder_paint: bool = True,
    ) -> bool:
        """Apply dimming to a widget batch with coalesced repaint scheduling."""
        changed = False
        for widget in widgets:
            if sip.isdeleted(widget):
                continue
            if skip_labels and isinstance(widget, QLabel):
                continue
            changed = self._set_widget_dimmed(
                widget,
                dimmed,
                preserve_placeholder_paint=preserve_placeholder_paint,
            ) or changed
        return changed
