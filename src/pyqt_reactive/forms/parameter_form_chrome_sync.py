"""Visual synchronization authority for parameter form manager chrome."""

from __future__ import annotations

from typing import Any, Set

from pyqt_reactive.services.field_change_dispatcher import FieldChangeDispatcher, FieldChangeEvent


class ParameterFormChromeSync:
    """Synchronizes labels, groupboxes, provenance controls, and widget state."""

    def __init__(self, manager: Any) -> None:
        self.manager = manager

    def after_model_field_change(self, param_name: str, full_path: str) -> None:
        self.manager.queue_field_flash(full_path)
        self.changed_field_visuals(param_name)

    def changed_field_visuals(self, param_name: str) -> None:
        self.update_label_styling(param_name)
        self.update_owning_groupbox_dirty_marker()
        self.update_provenance_button_visibility()
        for field_name in self.manager.reset_buttons:
            self.manager._update_reset_button_styling(field_name)

    def enabled_field_visuals(self, value: Any) -> None:
        self.manager._enabled_field_styling_service.on_enabled_field_changed(
            self.manager, "enabled", value
        )

    def update_owning_groupbox_dirty_marker(self) -> None:
        from pyqt_reactive.widgets.shared.clickable_help_components import GroupBoxWithHelp

        manager = self.manager
        groupbox = manager.form_tree.owning_groupbox(manager)
        if not isinstance(groupbox, GroupBoxWithHelp):
            return

        prefix = manager.field_id + "." if manager.field_id else ""
        if prefix:
            has_dirty = any(field.startswith(prefix) for field in manager.state.dirty_fields)
            has_sig_diff = any(field.startswith(prefix) for field in manager.state.signature_diff_fields)
        else:
            has_dirty = bool(manager.state.dirty_fields)
            has_sig_diff = bool(manager.state.signature_diff_fields)

        groupbox.set_dirty_marker(has_dirty, has_sig_diff)

    def update_provenance_button_visibility(self) -> None:
        from pyqt_reactive.widgets.shared.clickable_help_components import GroupBoxWithHelp
        from pyqt_reactive.widgets.shared.clickable_help_components import ProvenanceButton

        groupbox = self.manager.form_tree.owning_groupbox(self.manager)
        if isinstance(groupbox, GroupBoxWithHelp):
            for widget in groupbox.title_layout.findChildren(ProvenanceButton):
                widget.setVisible(widget._has_provenance())
                break

    def update_label_styling(self, param_name: str) -> None:
        from pyqt_reactive.widgets.shared.clickable_help_components import GroupBoxWithHelp

        manager = self.manager
        dotted_path = f"{manager.field_id}.{param_name}" if manager.field_id else param_name
        should_underline = self._path_or_descendant_in(
            dotted_path,
            manager.state.signature_diff_fields,
        )
        is_dirty = self._path_or_descendant_in(
            dotted_path,
            manager.state.dirty_fields,
        )

        if param_name in manager.labels:
            label = manager.labels[param_name]
            label.set_underline(should_underline)
            label.set_dirty_indicator(is_dirty)

        widget = manager.widgets.get(param_name)
        if isinstance(widget, GroupBoxWithHelp):
            widget.set_dirty_marker(is_dirty, should_underline)
        from pyqt_reactive.protocols.widget_protocols import ChildFieldChromeRefreshable
        if isinstance(widget, ChildFieldChromeRefreshable):
            widget.refresh_child_field_chrome()

    @staticmethod
    def _path_or_descendant_in(path: str, paths: set[str]) -> bool:
        if path in paths:
            return True
        prefix = f"{path}."
        return any(candidate.startswith(prefix) for candidate in paths)

    def state_changed(self) -> None:
        for param_name in set(self.manager.labels) | set(self.manager.widgets):
            self.update_label_styling(param_name)

        for nested_manager in self.manager.nested_managers.values():
            nested_manager.chrome_sync.state_changed()

    def update_groupbox_dirty_markers(
        self,
        dirty_prefixes: set[str],
        sig_diff_prefixes: set[str] | None = None,
    ) -> None:
        sig_diff_prefixes = sig_diff_prefixes or set()

        for _, nested_manager, groupbox in self.manager.form_tree.direct_child_groupboxes():
            prefix = nested_manager.field_id
            groupbox.set_dirty_marker(
                prefix in dirty_prefixes,
                prefix in sig_diff_prefixes,
            )

        for nested_manager in self.manager.nested_managers.values():
            nested_manager.chrome_sync.update_groupbox_dirty_markers(
                dirty_prefixes, sig_diff_prefixes
            )

    def refresh_field_in_tree(self, field_name: str) -> None:
        if field_name in self.manager.widgets:
            self.manager._parameter_ops_service.refresh_single_placeholder(self.manager, field_name)
        for nested_manager in self.manager.nested_managers.values():
            nested_manager.chrome_sync.refresh_field_in_tree(field_name)

    def refresh_widgets_from_state(self) -> None:
        from pyqt_reactive.protocols.widget_protocols import ValueSettable

        manager = self.manager
        for param_name, widget in manager.widgets.items():
            if isinstance(widget, ValueSettable):
                dotted_path = f"{manager.field_id}.{param_name}" if manager.field_id else param_name
                if dotted_path in manager.state.parameters:
                    value = manager.state.parameters.get(dotted_path)
                    manager._widget_service.update_widget_value(widget, value, param_name, False, manager)

        for nested_manager in manager.nested_managers.values():
            nested_manager.chrome_sync.refresh_widgets_from_state()

    def refresh_widgets_for_paths(self, paths: Set[str]) -> None:
        """Refresh value widgets and inherited placeholders for exact ObjectState paths."""
        from pyqt_reactive.protocols.widget_protocols import (
            ResolvedValuePreviewSettable,
            ValueSettable,
        )

        manager = self.manager
        missing = object()
        refreshed_container_paths: set[str] = set()

        for path in paths:
            if "." in path:
                path_prefix, leaf_field = path.rsplit(".", 1)
            else:
                path_prefix = ""
                leaf_field = path

            owner_field = self._direct_child_field_for_path(path)
            if owner_field is not None:
                owner_path = (
                    f"{manager.field_id}.{owner_field}"
                    if manager.field_id
                    else owner_field
                )
                if owner_path not in refreshed_container_paths:
                    owner_widget = manager.widgets.get(owner_field)
                    if isinstance(owner_widget, ValueSettable):
                        raw_value = manager.state.parameters.get(owner_path, missing)
                        if raw_value is not missing:
                            manager._widget_service.update_widget_value(
                                owner_widget,
                                raw_value,
                                owner_field,
                                True,
                                manager,
                            )
                    if isinstance(owner_widget, ResolvedValuePreviewSettable):
                        owner_widget.set_resolved_value_preview(
                            manager.state.get_resolved_value(owner_path)
                        )
                    if owner_widget is not None:
                        self.update_label_styling(owner_field)
                        refreshed_container_paths.add(owner_path)

            if path_prefix == manager.field_id:
                widget = manager.widgets.get(leaf_field)
                if isinstance(widget, ValueSettable):
                    value = manager.state.parameters.get(path, missing)
                    if value is not missing:
                        skip_context_behavior = value is None
                        manager._widget_service.update_widget_value(
                            widget,
                            value,
                            leaf_field,
                            skip_context_behavior,
                            manager,
                        )
                        if value is None:
                            manager._parameter_ops_service.refresh_single_placeholder(
                                manager,
                                leaf_field,
                            )

        for nested_manager in manager.nested_managers.values():
            nested_manager.chrome_sync.refresh_widgets_for_paths(paths)

    def _direct_child_field_for_path(self, path: str) -> str | None:
        manager = self.manager
        if manager.field_id:
            prefix = f"{manager.field_id}."
            if not path.startswith(prefix):
                return None
            remainder = path[len(prefix):]
        else:
            remainder = path

        if "." not in remainder:
            return None

        return remainder.split(".", 1)[0]

    def dispatch_reset(self, param_name: str) -> None:
        dotted_path = f"{self.manager.field_id}.{param_name}" if self.manager.field_id else param_name
        reset_value = self.manager.state.parameters.get(dotted_path)
        event = FieldChangeEvent(param_name, reset_value, self.manager, is_reset=True)
        FieldChangeDispatcher.instance().dispatch(event)
