"""Visual synchronization authority for parameter form manager chrome."""

from __future__ import annotations

from typing import Any, Set

from objectstate import DottedFieldPath
from pyqt_reactive.animation.flash_trace import flash_trace
from pyqt_reactive.services.field_change_dispatcher import FieldChangeDispatcher, FieldChangeEvent


class ParameterFormChromeSync:
    """Synchronizes labels, groupboxes, provenance controls, and widget state."""

    def __init__(self, manager: Any) -> None:
        self.manager = manager

    def after_model_field_change(
        self,
        param_name: str,
        full_path: str,
        *,
        queue_flash: bool = True,
        changed_paths: Set[str] | None = None,
        refreshed_compound_owner_paths: set[str] | None = None,
    ) -> None:
        owns_child_flash = self._field_widget_owns_child_flash(param_name)
        flash_trace(
            "chrome.after_model",
            manager=self.manager.field_id,
            param=param_name,
            path=full_path,
            queue_flash=queue_flash,
            owns_child_flash=owns_child_flash,
        )
        if queue_flash and not owns_child_flash:
            self.manager.queue_field_flash(full_path)
        self.changed_field_visuals(
            param_name,
            changed_paths,
            refreshed_compound_owner_paths,
        )

    def _field_widget_owns_child_flash(self, param_name: str) -> bool:
        from pyqt_reactive.protocols.widget_protocols import (
            ChildFieldNavigationTargetProvider,
            ChildFieldSemanticChromeRefreshable,
            ChildSubfieldNavigationTargetProvider,
        )

        widget = self.manager.widgets.get(param_name)
        return isinstance(
            widget,
            (
                ChildFieldNavigationTargetProvider,
                ChildFieldSemanticChromeRefreshable,
                ChildSubfieldNavigationTargetProvider,
            ),
        )

    def changed_field_visuals(
        self,
        param_name: str,
        changed_paths: Set[str] | None = None,
        refreshed_compound_owner_paths: set[str] | None = None,
    ) -> None:
        refreshed_compound_owner_paths = refreshed_compound_owner_paths or set()
        self.update_label_styling(
            param_name,
            changed_paths,
            refresh_compound_semantics=(
                self._owner_path(param_name).value not in refreshed_compound_owner_paths
            ),
        )
        self.update_owning_groupbox_dirty_marker()
        self.update_provenance_button_visibility()
        for field_name in self.manager.reset_buttons:
            self.manager._update_reset_button_styling(field_name)

    def enabled_field_visuals(self, value: Any) -> None:
        from python_introspect import Enableable

        self.manager._enabled_field_styling_service.on_enabled_field_changed(
            self.manager, Enableable.require_parameter_name(), value
        )

    def update_owning_groupbox_dirty_marker(self) -> None:
        from pyqt_reactive.widgets.shared.clickable_help_components import GroupBoxWithHelp

        manager = self.manager
        groupbox = manager.form_tree.owning_groupbox(manager)
        if not isinstance(groupbox, GroupBoxWithHelp):
            return

        if manager.field_id:
            owner_path = DottedFieldPath(manager.field_id)
            has_dirty = owner_path.contains_any(manager.state.dirty_fields)
            has_sig_diff = owner_path.contains_any(manager.state.signature_diff_fields)
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

    def update_label_styling(
        self,
        param_name: str,
        changed_paths: Set[str] | None = None,
        *,
        refresh_compound_semantics: bool = True,
    ) -> None:
        from pyqt_reactive.widgets.shared.clickable_help_components import GroupBoxWithHelp
        from objectstate.time_travel_profile import TimeTravelProfiler

        manager = self.manager
        with TimeTravelProfiler.phase(
            "pyqt.chrome.update_label_styling",
            manager_field_id=manager.field_id,
            param_name=param_name,
        ):
            dotted_path = self._owner_path(param_name)
            should_underline = dotted_path.contains_any(manager.state.signature_diff_fields)
            is_dirty = dotted_path.contains_any(manager.state.dirty_fields)

            if param_name in manager.labels:
                label = manager.labels[param_name]
                label.set_underline(should_underline)
                label.set_dirty_indicator(is_dirty)

            widget = manager.widgets.get(param_name)
            if isinstance(widget, GroupBoxWithHelp):
                widget.set_dirty_marker(is_dirty, should_underline)
            if refresh_compound_semantics:
                self._refresh_compound_widget_semantics(
                    widget,
                    self._compound_child_owner_paths(param_name, changed_paths),
                )

    def _owner_path(self, param_name: str) -> DottedFieldPath:
        manager = self.manager
        return DottedFieldPath(
            f"{manager.field_id}.{param_name}" if manager.field_id else param_name
        )

    def _compound_child_owner_paths(
        self,
        param_name: str,
        changed_paths: Set[str] | None,
    ) -> tuple[DottedFieldPath, ...] | None:
        if changed_paths is None:
            return None

        owner_path = self._owner_path(param_name)
        child_paths: list[DottedFieldPath] = []
        seen: set[str] = set()
        for changed_path in changed_paths:
            if changed_path == owner_path.value:
                return None
            child_field = owner_path.direct_child_name(changed_path)
            if child_field is None:
                continue
            child_path = owner_path.child(child_field)
            if child_path.value not in seen:
                seen.add(child_path.value)
                child_paths.append(child_path)
        return tuple(child_paths)

    def _refresh_compound_widget_semantics(
        self,
        widget,
        child_owner_paths: tuple[DottedFieldPath, ...] | None,
    ) -> None:
        from pyqt_reactive.protocols.widget_protocols import (
            ChildFieldChromeRefreshable,
            ChildFieldSemanticChromeRefreshable,
        )
        from objectstate.time_travel_profile import TimeTravelProfiler

        with TimeTravelProfiler.phase(
            "pyqt.chrome.refresh_compound_widget_semantics",
            manager_field_id=self.manager.field_id,
            widget_type=type(widget).__qualname__ if widget is not None else None,
        ):
            if isinstance(widget, ChildFieldChromeRefreshable):
                widget.refresh_child_field_chrome(child_owner_paths)
            if isinstance(widget, ChildFieldSemanticChromeRefreshable):
                semantic_owner_paths = widget.child_field_semantic_owner_paths()
                if child_owner_paths is not None:
                    child_owner_path_set = set(child_owner_paths)
                    semantic_owner_paths = tuple(
                        owner_path
                        for owner_path in semantic_owner_paths
                        if owner_path in child_owner_path_set
                    )
                for child_owner_path in semantic_owner_paths:
                    widget.refresh_child_field_semantics(
                        child_owner_path,
                        self.manager.state.subfield_semantics(child_owner_path),
                    )

    def state_changed(self) -> None:
        for param_name in set(self.manager.labels) | set(self.manager.widgets):
            self.update_label_styling(param_name)

        for nested_manager in self.manager.nested_managers.values():
            nested_manager.chrome_sync.state_changed()

    def state_changed_for_paths(
        self,
        paths: Set[str],
        refreshed_compound_owner_paths: set[str] | None = None,
    ) -> None:
        """Refresh dirty/signature chrome for the ObjectState paths that changed."""
        manager = self.manager
        refreshed_compound_owner_paths = (
            refreshed_compound_owner_paths
            if refreshed_compound_owner_paths is not None
            else set()
        )
        refreshed_fields: set[str] = set()

        for path in paths:
            owner_field = self._direct_child_field_for_path(path)
            if owner_field is not None:
                refreshed_fields.add(owner_field)

            if "." in path:
                path_prefix, leaf_field = path.rsplit(".", 1)
            else:
                path_prefix = ""
                leaf_field = path
            if path_prefix == manager.field_id:
                refreshed_fields.add(leaf_field)

        for param_name in refreshed_fields:
            owner_path = self._owner_path(param_name).value
            refresh_compound_semantics = owner_path not in refreshed_compound_owner_paths
            refreshed_compound_owner_paths.add(owner_path)
            self.update_label_styling(
                param_name,
                paths,
                refresh_compound_semantics=refresh_compound_semantics,
            )

        self.update_owning_groupbox_dirty_marker()
        self.update_provenance_button_visibility()
        for field_name in refreshed_fields & set(manager.reset_buttons):
            manager._update_reset_button_styling(field_name)

        for nested_manager, nested_paths in manager.form_tree.child_managers_for_paths(manager, paths):
            nested_manager.chrome_sync.state_changed_for_paths(
                nested_paths,
                refreshed_compound_owner_paths,
            )

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

    def refresh_widgets_for_paths(self, paths: Set[str]) -> set[str]:
        """Refresh value widgets and inherited placeholders for exact ObjectState paths."""
        from pyqt_reactive.protocols.widget_protocols import (
            RawResolvedValueSettable,
            ResolvedValuePreviewSettable,
            ValueSettable,
        )
        from objectstate.time_travel_profile import TimeTravelProfiler

        manager = self.manager
        missing = object()
        refreshed_container_paths: set[str] = set()
        refreshed_compound_owner_paths: set[str] = set()

        with TimeTravelProfiler.phase(
            "pyqt.chrome.refresh_widgets_local",
            manager_field_id=manager.field_id,
            paths=len(paths),
            widgets=len(manager.widgets),
        ):
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
                    if owner_path != path and owner_path not in refreshed_container_paths:
                        owner_widget = manager.widgets.get(owner_field)
                        raw_value = manager.state.parameters.get(owner_path, missing)
                        with TimeTravelProfiler.phase(
                            "pyqt.chrome.resolve_owner_value",
                            manager_field_id=manager.field_id,
                            owner_field=owner_field,
                        ):
                            resolved_value = manager.state.get_resolved_value(owner_path)
                        combined_update = (
                            raw_value is not missing
                            and raw_value != resolved_value
                            and isinstance(owner_widget, RawResolvedValueSettable)
                        )
                        if combined_update:
                            with TimeTravelProfiler.phase(
                                "pyqt.chrome.update_owner_raw_resolved_value",
                                manager_field_id=manager.field_id,
                                owner_field=owner_field,
                            ):
                                owner_widget.set_raw_value_with_resolved_preview(
                                    raw_value,
                                    resolved_value,
                                )
                        elif isinstance(owner_widget, ValueSettable):
                            if raw_value is not missing:
                                with TimeTravelProfiler.phase(
                                    "pyqt.chrome.update_owner_widget_value",
                                    manager_field_id=manager.field_id,
                                    owner_field=owner_field,
                                ):
                                    manager._widget_service.update_widget_value(
                                        owner_widget,
                                        raw_value,
                                        owner_field,
                                        True,
                                        manager,
                                    )
                        if (
                            not combined_update
                            and isinstance(owner_widget, ResolvedValuePreviewSettable)
                        ):
                            if raw_value is missing or raw_value != resolved_value:
                                with TimeTravelProfiler.phase(
                                    "pyqt.chrome.update_owner_resolved_preview",
                                    manager_field_id=manager.field_id,
                                    owner_field=owner_field,
                                ):
                                    owner_widget.set_resolved_value_preview(resolved_value)
                        if owner_widget is not None:
                            self._refresh_compound_widget_semantics(
                                owner_widget,
                                self._compound_child_owner_paths(owner_field, paths),
                            )
                            refreshed_container_paths.add(owner_path)
                            refreshed_compound_owner_paths.add(owner_path)

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

        with TimeTravelProfiler.phase(
            "pyqt.chrome.refresh_widgets_children",
            manager_field_id=manager.field_id,
            child_managers=len(manager.nested_managers),
        ):
            for nested_manager, nested_paths in manager.form_tree.child_managers_for_paths(manager, paths):
                refreshed_compound_owner_paths.update(
                    nested_manager.chrome_sync.refresh_widgets_for_paths(nested_paths)
                    or set()
                )

        return refreshed_compound_owner_paths

    def _direct_child_field_for_path(self, path: str) -> str | None:
        return self.manager.form_tree.direct_child_field_for_path(
            self.manager.field_id,
            path,
        )

    def dispatch_reset(self, param_name: str) -> None:
        dotted_path = f"{self.manager.field_id}.{param_name}" if self.manager.field_id else param_name
        reset_value = self.manager.state.parameters.get(dotted_path)
        event = FieldChangeEvent(param_name, reset_value, self.manager, is_reset=True)
        FieldChangeDispatcher.instance().dispatch(event)
