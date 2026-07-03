"""Tree index authority for nested parameter form managers."""

from __future__ import annotations

from typing import Any, Optional

from objectstate import DottedFieldPath
from PyQt6.QtWidgets import QWidget


class ParameterFormTreeIndex:
    """Indexes nested managers and groupbox widgets for a form-manager tree."""

    def __init__(self, root_manager: Any) -> None:
        self.root_manager = root_manager
        self._groupbox_cache: dict[str, Optional[QWidget]] = {}

    def root(self) -> Any:
        manager = self.root_manager
        while manager._parent_manager is not None:
            manager = manager._parent_manager
        return manager

    def owning_groupbox(self, manager: Any) -> Optional[QWidget]:
        parent = manager._parent_manager
        if parent is None:
            return None
        for name, nested in parent.nested_managers.items():
            if nested is manager:
                return parent.widgets.get(name)
        return None

    def nested_manager_for_prefix(self, prefix: str) -> Optional[Any]:
        return self._nested_manager_recursive(prefix, self.root_manager)

    def matching_prefix(self, path: str) -> Optional[str]:
        return self._matching_prefix_recursive(path, self.root_manager)

    def groupbox_for_prefix(self, prefix: str) -> Optional[QWidget]:
        if prefix not in self._groupbox_cache:
            self._groupbox_cache[prefix] = self._groupbox_recursive(prefix, self.root_manager)
        return self._groupbox_cache[prefix]

    def direct_child_groupboxes(self) -> list[tuple[str, Any, QWidget]]:
        result = []
        for param_name, nested_manager in self.root_manager.nested_managers.items():
            groupbox = self.root_manager.widgets.get(param_name)
            if groupbox is not None:
                result.append((param_name, nested_manager, groupbox))
        return result

    def paths_for_manager(self, manager: Any, paths: set[str]) -> set[str]:
        """Return changed paths whose scope intersects a nested manager."""
        field_id = manager.field_id
        if not field_id:
            return set(paths)
        return {
            path
            for path in paths
            if self.path_intersects_field_scope(path, field_id)
        }

    def child_managers_for_paths(self, manager: Any, paths: set[str]) -> tuple[tuple[Any, set[str]], ...]:
        """Return direct child managers whose field scope intersects changed paths."""
        routed_paths: dict[int, tuple[Any, set[str]]] = {}
        for path in paths:
            child_field = self.direct_child_field_for_path(manager.field_id, path)
            if child_field is None:
                continue
            nested_manager = manager.nested_managers.get(child_field)
            if nested_manager is None:
                continue
            manager_id = id(nested_manager)
            if manager_id not in routed_paths:
                routed_paths[manager_id] = (nested_manager, set())
            routed_paths[manager_id][1].add(path)
        return tuple(routed_paths.values())

    @staticmethod
    def direct_child_field_for_path(field_id: str, path: str) -> Optional[str]:
        """Return the direct child field owning a dotted ObjectState path."""
        if field_id:
            return DottedFieldPath(field_id).direct_child_name(path)

        if not path:
            return None
        return path.split(".", 1)[0].split("[", 1)[0] or None

    @staticmethod
    def path_intersects_field_scope(path: str, field_id: str) -> bool:
        path_field = DottedFieldPath(path)
        field = DottedFieldPath(field_id)
        return path_field.contains_path(field) or field.contains_path(path_field)

    @staticmethod
    def path_belongs_to_field_scope(path: str, field_id: str) -> bool:
        return DottedFieldPath(field_id).contains_path(path)

    def _nested_manager_recursive(self, prefix: str, manager: Any) -> Optional[Any]:
        for nested_manager in manager.nested_managers.values():
            if nested_manager.field_id == prefix:
                return nested_manager
            result = self._nested_manager_recursive(prefix, nested_manager)
            if result is not None:
                return result
        return None

    def _matching_prefix_recursive(self, path: str, manager: Any) -> Optional[str]:
        for nested_manager in manager.nested_managers.values():
            prefix = nested_manager.field_id
            if self.path_belongs_to_field_scope(path, prefix):
                deeper = self._matching_prefix_recursive(path, nested_manager)
                return deeper if deeper else prefix
        return None

    def _groupbox_recursive(self, prefix: str, manager: Any) -> Optional[QWidget]:
        for param_name, nested_manager in manager.nested_managers.items():
            if nested_manager.field_id == prefix:
                return manager.widgets.get(param_name)
            result = self._groupbox_recursive(prefix, nested_manager)
            if result is not None:
                return result
        return None
