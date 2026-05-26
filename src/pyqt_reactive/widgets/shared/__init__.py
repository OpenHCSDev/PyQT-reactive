"""
Shared widget utilities and components.
"""

from __future__ import annotations

import importlib
from typing import Any

_EXPORTS = {
    "ScrollableFormMixin": (
        "pyqt_reactive.widgets.shared.scrollable_form_mixin",
        "ScrollableFormMixin",
    ),
    "TabbedFormWidget": (
        "pyqt_reactive.widgets.shared.tabbed_form_widget",
        "TabbedFormWidget",
    ),
    "TabConfig": (
        "pyqt_reactive.widgets.shared.tabbed_form_widget",
        "TabConfig",
    ),
    "TabbedFormConfig": (
        "pyqt_reactive.widgets.shared.tabbed_form_widget",
        "TabbedFormConfig",
    ),
    "ActionTabSpec": (
        "pyqt_reactive.widgets.shared.action_tabbed_window_body",
        "ActionTabSpec",
    ),
    "ActionTabbedWindowBody": (
        "pyqt_reactive.widgets.shared.action_tabbed_window_body",
        "ActionTabbedWindowBody",
    ),
    "BaseManagedWindow": (
        "pyqt_reactive.widgets.shared.base_form_dialog",
        "BaseManagedWindow",
    ),
    "BaseFormDialog": (
        "pyqt_reactive.widgets.shared.base_form_dialog",
        "BaseFormDialog",
    ),
    "DirtyWindowPresentation": (
        "pyqt_reactive.widgets.shared.dirty_window_presenter",
        "DirtyWindowPresentation",
    ),
    "DirtyWindowPresenter": (
        "pyqt_reactive.widgets.shared.dirty_window_presenter",
        "DirtyWindowPresenter",
    ),
    "FormWindowActionHeader": (
        "pyqt_reactive.widgets.shared.form_window_action_header",
        "FormWindowActionHeader",
    ),
    "HeaderAction": (
        "pyqt_reactive.widgets.shared.form_window_action_header",
        "HeaderAction",
    ),
    "HeaderActionGroup": (
        "pyqt_reactive.widgets.shared.form_window_action_header",
        "HeaderActionGroup",
    ),
    "TearOffTabWidget": (
        "pyqt_reactive.widgets.shared.tear_off_tab_widget",
        "TearOffTabWidget",
    ),
    "FloatingTabWindow": (
        "pyqt_reactive.widgets.shared.tear_off_tab_widget",
        "FloatingTabWindow",
    ),
    "TearOffTabBar": (
        "pyqt_reactive.widgets.shared.tear_off_tab_widget",
        "TearOffTabBar",
    ),
    "TearOffRegistry": (
        "pyqt_reactive.widgets.shared.tear_off_registry",
        "TearOffRegistry",
    ),
    "ResponsiveTwoRowWidget": (
        "pyqt_reactive.widgets.shared.responsive_layout_widgets",
        "ResponsiveTwoRowWidget",
    ),
    "ResponsiveParameterRow": (
        "pyqt_reactive.widgets.shared.responsive_layout_widgets",
        "ResponsiveParameterRow",
    ),
    "StagedWrapLayout": (
        "pyqt_reactive.widgets.shared.responsive_layout_widgets",
        "StagedWrapLayout",
    ),
    "ResponsiveGroupBoxTitle": (
        "pyqt_reactive.widgets.shared.responsive_groupbox_title",
        "ResponsiveGroupBoxTitle",
    ),
    "TreeNode": (
        "pyqt_reactive.widgets.shared.tree_sync_adapter",
        "TreeNode",
    ),
    "TreeSyncAdapter": (
        "pyqt_reactive.widgets.shared.tree_sync_adapter",
        "TreeSyncAdapter",
    ),
    "TreeItemKeyBuilderABC": (
        "pyqt_reactive.widgets.shared.tree_state_adapter",
        "TreeItemKeyBuilderABC",
    ),
    "DictPayloadTreeItemKeyBuilder": (
        "pyqt_reactive.widgets.shared.tree_state_adapter",
        "DictPayloadTreeItemKeyBuilder",
    ),
    "TreeStateAdapter": (
        "pyqt_reactive.widgets.shared.tree_state_adapter",
        "TreeStateAdapter",
    ),
    "TreeRebuildCoordinator": (
        "pyqt_reactive.widgets.shared.tree_rebuild_coordinator",
        "TreeRebuildCoordinator",
    ),
    "ScopeColorSchemeReceiver": (
        "pyqt_reactive.widgets.shared.scope_color_receiver",
        "ScopeColorSchemeReceiver",
    ),
    "ScopedTableWidget": (
        "pyqt_reactive.widgets.shared.scoped_table_widget",
        "ScopedTableWidget",
    ),
    "ManagerHeaderParts": (
        "pyqt_reactive.widgets.shared.manager_ui_scaffold",
        "ManagerHeaderParts",
    ),
    "create_manager_header": (
        "pyqt_reactive.widgets.shared.manager_ui_scaffold",
        "create_manager_header",
    ),
    "setup_vertical_manager_layout": (
        "pyqt_reactive.widgets.shared.manager_ui_scaffold",
        "setup_vertical_manager_layout",
    ),
    "KillOperationPlan": (
        "pyqt_reactive.widgets.shared.zmq_server_browser_widget",
        "KillOperationPlan",
    ),
    "ZMQServerBrowserWidgetABC": (
        "pyqt_reactive.widgets.shared.zmq_server_browser_widget",
        "ZMQServerBrowserWidgetABC",
    ),
}

__all__ = [
    *_EXPORTS,
]


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        module_name, attr_name = _EXPORTS[name]
        module = importlib.import_module(module_name)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
