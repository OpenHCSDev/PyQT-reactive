"""Root-scoped progressive form construction regressions."""

from __future__ import annotations

from dataclasses import dataclass, field, make_dataclass
from time import monotonic
from types import SimpleNamespace

import pytest
from python_introspect import Enableable


@dataclass
class _TransactionLeaf:
    value_1: int = 1
    value_2: int = 2
    value_3: int = 3
    value_4: int = 4
    value_5: int = 5
    value_6: int = 6


@dataclass
class _TransactionRoot:
    first: _TransactionLeaf = field(default_factory=_TransactionLeaf)
    second: _TransactionLeaf = field(default_factory=_TransactionLeaf)


@dataclass
class _FlatRoot:
    value_1: int = 1
    value_2: int = 2
    value_3: int = 3
    value_4: int = 4
    value_5: int = 5
    value_6: int = 6


@dataclass(frozen=True)
class _ProgressiveChromeConfig(Enableable):
    value_1: int = 1
    value_2: int = 2
    value_3: int = 3
    value_4: int = 4
    value_5: int = 5
    value_6: int = 6


@dataclass
class _OptionalNestedRoot:
    optional_leaf: _TransactionLeaf | None = None
    value_1: int = 1
    value_2: int = 2
    value_3: int = 3
    value_4: int = 4
    value_5: int = 5
    value_6: int = 6


def _manager_tree(root):
    yield root
    for nested in root.nested_managers.values():
        yield from _manager_tree(nested)


def _created_row_count(root) -> int:
    return sum(len(manager.widgets) for manager in _manager_tree(root))


def _declared_row_count(root) -> int:
    return sum(
        len(manager.form_structure.parameters) for manager in _manager_tree(root)
    )


def _wait_until(qapp, predicate, timeout_s: float = 2.0) -> None:
    deadline = monotonic() + timeout_s
    while monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
    raise AssertionError("Progressive form construction did not settle.")


def test_nested_forms_share_one_sync_budget_and_finalize_once(qapp, monkeypatch):
    """Nested forms spend one root quota and perform one semantic refresh."""
    from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type

    from pyqt_reactive.forms.form_init_service import BuildConfig
    from pyqt_reactive.forms.parameter_form_manager import (
        FormManagerConfig,
        ParameterFormManager,
    )
    from pyqt_reactive.services.parameter_ops_service import ParameterOpsService
    from pyqt_reactive.theming import ColorScheme

    set_base_config_type(_TransactionRoot)
    ObjectStateRegistry.clear()
    refresh_calls = []
    original_refresh = ParameterOpsService.refresh_with_live_context

    def counted_refresh(service, manager, defer=False):
        refresh_calls.append((manager, defer))
        return original_refresh(service, manager, defer=defer)

    monkeypatch.setattr(
        ParameterOpsService,
        "refresh_with_live_context",
        counted_refresh,
    )
    manager = ParameterFormManager(
        ObjectState(_TransactionRoot()),
        FormManagerConfig(
            color_scheme=ColorScheme(),
            use_scroll_area=False,
        ),
    )
    transaction = manager._form_build_transaction
    completed = []
    registered_completion_callbacks = []
    manager.form_build_completed.connect(lambda: completed.append(True))
    assert manager.register_form_build_completion_callback(
        lambda: registered_completion_callbacks.append(True)
    )

    try:
        assert BuildConfig().initial_sync_widgets == 5
        assert _created_row_count(manager) == 5

        _wait_until(
            qapp,
            lambda: (
                _created_row_count(manager) == _declared_row_count(manager)
                and transaction.finalization_count == 1
            ),
        )

        assert _created_row_count(manager) == 14
        assert refresh_calls == [(manager, False)]
        assert manager.styleSheet()
        assert all(
            not nested.styleSheet()
            for nested in tuple(_manager_tree(manager))[1:]
        )
        for _ in range(10):
            qapp.processEvents()
        assert transaction.finalization_count == 1
        assert manager.form_build_complete is True
        assert completed == [True]
        assert registered_completion_callbacks == [True]
        assert not manager.register_form_build_completion_callback(lambda: None)
        assert refresh_calls == [(manager, False)]
    finally:
        manager.deleteLater()
        qapp.processEvents()
        ObjectStateRegistry.clear()


def test_visible_progressive_rows_receive_chrome_before_finalization(qapp):
    """Materialized lazy fields are styled before the form tree completes."""
    from objectstate import (
        LazyDataclassFactory,
        ObjectState,
        ObjectStateRegistry,
        set_base_config_type,
    )

    from pyqt_reactive.forms.parameter_form_manager import (
        FormManagerConfig,
        ParameterFormManager,
    )
    from pyqt_reactive.protocols import PlaceholderStateTrackable
    from pyqt_reactive.theming import ColorScheme

    set_base_config_type(_ProgressiveChromeConfig)
    ObjectStateRegistry.clear()
    lazy_config_type = LazyDataclassFactory.make_lazy_simple(
        _ProgressiveChromeConfig,
    )
    progressive_root_type = make_dataclass(
        "_ProgressiveChromeRoot",
        [
            (
                "config",
                lazy_config_type,
                field(
                    default_factory=lambda: lazy_config_type(
                        enabled=False,
                        value_1=101,
                    ),
                ),
            ),
        ],
        frozen=True,
    )
    set_base_config_type(progressive_root_type)
    state = ObjectState(
        progressive_root_type(),
        scope_id="progressive-chrome-child",
    )
    manager = ParameterFormManager(
        state,
        FormManagerConfig(
            color_scheme=ColorScheme(),
            use_scroll_area=False,
        ),
    )
    transaction = manager._form_build_transaction

    try:
        assert transaction.finalization_count == 0
        assert tuple(manager.widgets) == ("config",)
        nested_manager = manager.nested_managers["config"]
        assert tuple(nested_manager.widgets) == (
            "enabled",
            "value_1",
            "value_2",
            "value_3",
        )

        enabled_widget = nested_manager.widgets["enabled"]
        inherited_value_widget = nested_manager.widgets["value_2"]
        concrete_value_widget = nested_manager.widgets["value_1"]
        assert isinstance(enabled_widget, PlaceholderStateTrackable)
        assert isinstance(inherited_value_widget, PlaceholderStateTrackable)
        assert not enabled_widget.has_placeholder_state()
        assert enabled_widget.isChecked() is False
        assert inherited_value_widget.has_placeholder_state()
        assert concrete_value_widget.property("enabled_field_dimmed") is True
        assert concrete_value_widget.graphicsEffect() is not None

        _wait_until(
            qapp,
            lambda: transaction.finalization_count == 1,
        )

        assert manager._form_build_transaction.failure is None
        assert nested_manager.widgets["value_6"].has_placeholder_state()
    finally:
        manager.deleteLater()
        qapp.processEvents()
        ObjectStateRegistry.clear()


def test_deleting_progressive_root_cancels_unfinished_generation(qapp):
    """Manager-owned timers cannot finalize a deleted progressive form."""
    from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type
    from PyQt6 import sip

    from pyqt_reactive.forms.parameter_form_manager import (
        FormManagerConfig,
        ParameterFormManager,
    )
    from pyqt_reactive.theming import ColorScheme

    set_base_config_type(_FlatRoot)
    ObjectStateRegistry.clear()
    manager = ParameterFormManager(
        ObjectState(_FlatRoot()),
        FormManagerConfig(
            color_scheme=ColorScheme(),
            use_scroll_area=False,
        ),
    )
    transaction = manager._form_build_transaction

    sip.delete(manager)
    for _ in range(10):
        qapp.processEvents()

    assert transaction.finalization_count == 0
    assert transaction.cancelled is True
    assert manager._disposed is True
    ObjectStateRegistry.clear()


def test_disposing_progressive_root_cancels_hidden_form_work(qapp):
    """Closing a retained window stops work before QObject destruction."""
    from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type

    from pyqt_reactive.forms.parameter_form_manager import (
        FormManagerConfig,
        ParameterFormManager,
    )
    from pyqt_reactive.theming import ColorScheme

    set_base_config_type(_FlatRoot)
    ObjectStateRegistry.clear()
    manager = ParameterFormManager(
        ObjectState(_FlatRoot()),
        FormManagerConfig(
            color_scheme=ColorScheme(),
            use_scroll_area=False,
        ),
    )
    transaction = manager._form_build_transaction
    failures = []
    completions = []
    manager.form_build_failed.connect(failures.append)
    manager.form_build_completed.connect(lambda: completions.append(True))
    rows_before_disposal = _created_row_count(manager)

    try:
        manager.dispose()
        for _ in range(10):
            qapp.processEvents()

        assert manager.form_build_cancelled is True
        assert manager.form_build_complete is False
        assert manager.form_build_failure is None
        assert transaction.finalization_count == 0
        assert _created_row_count(manager) == rows_before_disposal
        assert failures == []
        assert completions == []
    finally:
        manager.deleteLater()
        qapp.processEvents()
        ObjectStateRegistry.clear()


def test_form_build_has_one_scheduling_and_finalization_authority():
    """Deleted per-manager scheduling mirrors cannot silently return."""
    import pyqt_reactive.forms.form_init_service as form_init_service
    from pyqt_reactive.forms.parameter_form_manager import ParameterFormManager

    assert not hasattr(ParameterFormManager, "should_use_async")
    assert not hasattr(ParameterFormManager, "ASYNC_WIDGET_CREATION")
    assert not hasattr(ParameterFormManager, "ASYNC_THRESHOLD")
    assert not hasattr(ParameterFormManager, "INITIAL_SYNC_WIDGETS")
    assert not hasattr(form_init_service, "InitialRefreshStrategy")
    assert not hasattr(form_init_service, "BuildPhase")
    assert not hasattr(form_init_service, "RefreshMode")


def test_async_widget_failure_is_published_without_finalizing(qapp, monkeypatch):
    """A later progressive-row failure is a form signal, not a Qt callback crash."""
    from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type

    from pyqt_reactive.forms.parameter_form_manager import (
        FormManagerConfig,
        ParameterFormManager,
    )
    from pyqt_reactive.theming import ColorScheme

    original_create = ParameterFormManager._create_widget_for_param

    def fail_sixth(manager, param_info):
        if param_info.name == "value_6":
            raise ValueError("deliberate progressive build failure")
        return original_create(manager, param_info)

    monkeypatch.setattr(
        ParameterFormManager,
        "_create_widget_for_param",
        fail_sixth,
    )
    set_base_config_type(_FlatRoot)
    ObjectStateRegistry.clear()
    manager = ParameterFormManager(
        ObjectState(_FlatRoot()),
        FormManagerConfig(
            color_scheme=ColorScheme(),
            use_scroll_area=False,
        ),
    )
    failures = []
    manager.form_build_failed.connect(failures.append)

    try:
        _wait_until(qapp, lambda: bool(failures))
        assert str(failures[0]) == "deliberate progressive build failure"
        assert manager._form_build_transaction.failure is failures[0]
        assert manager._form_build_transaction.finalization_count == 0
    finally:
        manager.deleteLater()
        qapp.processEvents()
        ObjectStateRegistry.clear()


def test_synchronous_widget_failure_balances_and_fails_root_transaction(qapp):
    """Initial-row failures use the same root transaction boundary as later rows."""
    from PyQt6.QtWidgets import QVBoxLayout, QWidget

    from pyqt_reactive.forms.form_init_service import (
        BuildConfig,
        FormBuildOrchestrator,
        FormBuildTransaction,
    )

    manager = QWidget()
    manager._parent_manager = None
    manager._pfm_seq = 1
    manager.field_id = "root"
    failures: list[Exception] = []
    manager.form_build_failed = SimpleNamespace(emit=failures.append)
    manager._enabled_field_styling_service = SimpleNamespace(
        invalidate_widget_cache=lambda _manager: None,
    )

    def fail_widget(_param_info):
        raise ValueError("deliberate synchronous build failure")

    manager._create_widget_for_param = fail_widget
    transaction = FormBuildTransaction(
        manager,
        BuildConfig(initial_sync_widgets=1),
    )
    manager._form_build_transaction = transaction
    layout = QVBoxLayout(manager)

    try:
        with pytest.raises(
            ValueError,
            match="deliberate synchronous build failure",
        ):
            FormBuildOrchestrator().build_widgets(
                manager,
                layout,
                [SimpleNamespace(name="value")],
            )

        assert transaction._registration_depth == 0
        assert transaction.failure is failures[0]
        assert transaction.finalization_count == 0
    finally:
        manager.deleteLater()
        qapp.processEvents()


def test_batch_callback_failure_is_published_without_finalizing(qapp):
    """Timer-owned batch callbacks cannot escape the transaction boundary."""
    from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type

    from pyqt_reactive.forms.parameter_form_manager import (
        FormManagerConfig,
        ParameterFormManager,
    )
    from pyqt_reactive.theming import ColorScheme

    set_base_config_type(_FlatRoot)
    ObjectStateRegistry.clear()
    manager = ParameterFormManager(
        ObjectState(_FlatRoot()),
        FormManagerConfig(
            color_scheme=ColorScheme(),
            use_scroll_area=False,
        ),
    )
    failures = []
    manager.form_build_failed.connect(failures.append)

    def fail_batch(_manager, _materialized_widgets):
        raise ValueError("deliberate batch callback failure")

    manager._enabled_field_styling_service.apply_materialized_enabled_styling = (
        fail_batch
    )

    try:
        _wait_until(qapp, lambda: bool(failures))
        assert str(failures[0]) == "deliberate batch callback failure"
        assert manager._form_build_transaction.failure is failures[0]
        assert manager._form_build_transaction.finalization_count == 0
    finally:
        manager.deleteLater()
        qapp.processEvents()
        ObjectStateRegistry.clear()


def test_post_build_failure_is_published_without_finalizing(qapp, monkeypatch):
    """Semantic finalization shares the transaction's Qt callback boundary."""
    from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type

    from pyqt_reactive.forms.form_init_service import FormBuildOrchestrator
    from pyqt_reactive.forms.parameter_form_manager import (
        FormManagerConfig,
        ParameterFormManager,
    )
    from pyqt_reactive.theming import ColorScheme

    def fail_finalization(_orchestrator, _manager):
        raise ValueError("deliberate post-build failure")

    monkeypatch.setattr(
        FormBuildOrchestrator,
        "_execute_post_build_sequence",
        fail_finalization,
    )
    set_base_config_type(_FlatRoot)
    ObjectStateRegistry.clear()
    manager = ParameterFormManager(
        ObjectState(_FlatRoot()),
        FormManagerConfig(
            color_scheme=ColorScheme(),
            use_scroll_area=False,
        ),
    )
    failures = []
    manager.form_build_failed.connect(failures.append)

    try:
        _wait_until(qapp, lambda: bool(failures))
        assert str(failures[0]) == "deliberate post-build failure"
        assert manager._form_build_transaction.failure is failures[0]
        assert manager._form_build_transaction.finalization_count == 0
    finally:
        manager.deleteLater()
        qapp.processEvents()
        ObjectStateRegistry.clear()


def test_optional_nested_plain_groupbox_completes_dirty_chrome_finalization(qapp):
    """Optional structural containers do not claim rich dirty-marker chrome."""
    from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type
    from PyQt6.QtWidgets import QGroupBox

    from pyqt_reactive.forms.parameter_form_manager import (
        FormManagerConfig,
        ParameterFormManager,
    )
    from pyqt_reactive.theming import ColorScheme
    from pyqt_reactive.widgets.shared.clickable_help_components import (
        GroupBoxWithHelp,
    )
    from pyqt_reactive.widgets.shared.config_hierarchy_tree import (
        ConfigHierarchyTreeHelper,
    )

    set_base_config_type(_OptionalNestedRoot)
    ObjectStateRegistry.clear()
    state = ObjectState(_OptionalNestedRoot())
    manager = ParameterFormManager(
        state,
        FormManagerConfig(
            color_scheme=ColorScheme(),
            use_scroll_area=False,
        ),
    )
    tree_helper = ConfigHierarchyTreeHelper()
    tree_helper.create_tree_from_root_dataclass(
        root_dataclass=_OptionalNestedRoot,
        form_manager=manager,
        state=state,
        on_item_double_clicked=lambda _item, _column: None,
    )

    try:
        optional_container = manager.widgets["optional_leaf"]
        assert isinstance(optional_container, QGroupBox)
        assert not isinstance(optional_container, GroupBoxWithHelp)

        _wait_until(
            qapp,
            lambda: manager._form_build_transaction.finalization_count == 1,
        )

        assert manager._form_build_transaction.failure is None
    finally:
        tree_helper.cleanup_subscriptions()
        manager.deleteLater()
        qapp.processEvents()
        ObjectStateRegistry.clear()
