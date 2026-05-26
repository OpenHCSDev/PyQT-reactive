"""Tree index authority for nested parameter form managers."""

from __future__ import annotations

from typing import Any, Optional

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
            if path.startswith(prefix + ".") or path == prefix:
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
