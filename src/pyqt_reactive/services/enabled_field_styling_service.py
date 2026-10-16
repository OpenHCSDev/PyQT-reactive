"""Enabled Field Styling Service - Visual styling for enabled/disabled states."""

from objectstate import FieldProxy, FieldValue
from python_introspect import Enableable

import logging
from collections.abc import Iterable
from typing import Any
from weakref import WeakKeyDictionary

from objectstate.time_travel_profile import TimeTravelProfiler
from PyQt6 import sip
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget

from pyqt_reactive.protocols import PlaceholderStateTrackable, ValueGettable

logger = logging.getLogger(__name__)


class EnabledFieldStylingService:
    """
    Service for applying visual styling based on enabled field state.

    Backend fields own enablement. This owner keeps widget discovery and the
    last painted effective state, never an alternative data value.
    """

    def __init__(self):
        """Keep presentation resources bounded by their manager lifetimes."""
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

    def apply_materialized_enabled_styling(
        self,
        manager,
        materialized_widgets: Iterable[QWidget],
    ) -> None:
        """Style exact new value widgets before their form tree is attached."""
        direct_widgets = list(self._direct_widgets_by_manager.get(manager, ()))
        direct_widget_ids = {id(widget) for widget in direct_widgets}
        for widget in materialized_widgets:
            if (
                not isinstance(widget, ValueGettable)
                or sip.isdeleted(widget)
                or id(widget) in direct_widget_ids
            ):
                continue
            direct_widgets.append(widget)
            direct_widget_ids.add(id(widget))

        self._direct_widgets_by_manager[manager] = direct_widgets
        group_box = manager.form_tree.owning_groupbox(manager)
        if group_box is not None:
            self._value_widgets_by_container.pop(group_box, None)
        self._last_enabled_values.pop(manager, None)
        self.apply_initial_enabled_styling(manager)
    
    @staticmethod
    def _enabled_field(manager):
        return next((field for field in manager.fields.children if Enableable.is_parameter_key(field.name)), None)

    def apply_initial_enabled_styling(self, manager) -> None:
        """Paint this materialized scope from its canonical effective value."""
        if self._should_skip_optional_dataclass_styling(manager, "INITIAL ENABLED STYLING"):
            return
        self._last_enabled_values.pop(manager, None)
        field = self._enabled_field(manager)
        if field is not None:
            self._paint_enabled_scope(manager, field)

    def refresh_enabled_styling(self, manager) -> None:
        """Own the single enabled-paint traversal for this form subtree."""
        if self._should_skip_optional_dataclass_styling(manager, "REFRESH ENABLED STYLING"):
            return
        field = self._enabled_field(manager)
        if field is not None:
            self._paint_enabled_scope(manager, field)
        for nested_manager in manager.nested_managers.values():
            self.refresh_enabled_styling(nested_manager)

    def on_enabled_field_changed(self, manager, field: FieldProxy) -> None:
        """A changed enable declaration invalidates its scope and descendants."""
        if Enableable.is_parameter_key(field.name):
            self.refresh_enabled_styling(manager)

    @staticmethod
    def _is_enabled(field: FieldProxy) -> bool:
        value = field.value
        return FieldValue.of(value).has_value and bool(value)

    def _paint_enabled_scope(self, manager, field: FieldProxy) -> None:
        effective = self._is_enabled(field) and not self._is_any_ancestor_disabled(manager)
        if manager in self._last_enabled_values and self._last_enabled_values[manager] == effective:
            return
        self._last_enabled_values[manager] = effective
        direct_widgets = self._get_direct_widgets(manager)
        if manager.form_tree.owning_groupbox(manager) is not None:
            self._apply_nested_config_styling(manager, effective)
        else:
            self._apply_top_level_styling(manager, effective, direct_widgets)

    
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
                        from formbridge.forms.parameter_type_utils import ParameterTypeUtils
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

        all_widgets = self.widget_ops.get_all_value_widgets(manager)
        logger.debug(f"[GET_DIRECT_WIDGETS] field_id={manager.field_id}, total widgets found: {len(all_widgets)}, nested_managers: {list(manager.nested_managers.keys())}")

        nested_widget_ids: set[int] = set()
        for _, _, container in manager.form_tree.direct_child_groupboxes():
            nested_widget_ids.add(id(container))
            nested_widget_ids.update(
                id(widget)
                for widget in self.widget_ops.get_all_value_widgets(container)
            )

        direct_widgets = [
            widget
            for widget in all_widgets
            if not sip.isdeleted(widget) and id(widget) not in nested_widget_ids
        ]

        logger.debug(f"[GET_DIRECT_WIDGETS] field_id={manager.field_id}, returning {len(direct_widgets)} direct widgets")

        self._direct_widgets_by_manager[manager] = direct_widgets
        return direct_widgets
    
    def _is_any_ancestor_disabled(self, manager) -> bool:
        current = manager._parent_manager
        while current is not None:
            field = self._enabled_field(current)
            if field is not None and not self._is_enabled(field):
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

        should_dim = not resolved_value
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
        """Paint only this scope; refresh_enabled_styling owns descendant work."""
        self._set_widgets_dimmed(direct_widgets, not resolved_value, skip_labels=not resolved_value)


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
