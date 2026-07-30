"""Lazy materialization contracts for the generic action-tab body."""

from __future__ import annotations


def test_inactive_tab_materializes_once_on_first_activation(qapp):
    from PyQt6.QtWidgets import QLabel, QPushButton

    from pyqt_reactive.widgets.shared.action_tabbed_window_body import (
        ActionTabbedWindowBody,
        ActionTabMaterialization,
        ActionTabSpec,
    )

    body = ActionTabbedWindowBody()
    created = []
    materialized = []
    events = []
    body.tab_materialized.connect(
        lambda index, result: (
            materialized.append((index, result)),
            events.append(("materialized", index)),
        )
    )
    body.current_changed.connect(
        lambda index: events.append(("current_changed", index))
    )

    body.add_tab(ActionTabSpec("First", content=QLabel("first")))
    body.add_tab(
        ActionTabSpec(
            "Second",
            materialization_factory=lambda: (
                created.append(
                    ActionTabMaterialization(
                        QLabel("second"),
                        QPushButton("second actions"),
                    )
                )
                or created[-1]
            ),
        )
    )
    body.show()
    qapp.processEvents()

    assert body.is_materialized(0)
    assert not body.is_materialized(1)
    assert body.widget(1) is None
    assert created == []

    body.set_current_index(1)
    qapp.processEvents()

    assert body.is_materialized(1)
    assert body.widget(1) is created[0].content
    assert materialized == [(1, created[0])]
    assert created[0].actions.isVisible()
    assert events[-2:] == [("materialized", 1), ("current_changed", 1)]

    body.set_current_index(0)
    assert not created[0].actions.isVisible()
    body.set_current_index(1)
    qapp.processEvents()
    assert len(created) == 1
    assert materialized == [(1, created[0])]

    body.deleteLater()
    qapp.processEvents()


def test_first_lazy_tab_materializes_when_added(qapp):
    from PyQt6.QtWidgets import QLabel

    from pyqt_reactive.widgets.shared.action_tabbed_window_body import (
        ActionTabbedWindowBody,
        ActionTabMaterialization,
        ActionTabSpec,
    )

    body = ActionTabbedWindowBody()
    created = []
    body.add_tab(
        ActionTabSpec(
            "First",
            materialization_factory=lambda: (
                created.append(ActionTabMaterialization(QLabel("first")))
                or created[-1]
            ),
        )
    )

    assert len(created) == 1
    assert body.current_widget() is created[0].content
    body.deleteLater()
    qapp.processEvents()


def test_lazy_tab_factory_must_return_widget(qapp):
    import pytest
    from PyQt6.QtWidgets import QLabel

    from pyqt_reactive.widgets.shared.action_tabbed_window_body import (
        ActionTabbedWindowBody,
        ActionTabSpec,
    )

    body = ActionTabbedWindowBody()
    body.add_tab(ActionTabSpec("First", content=QLabel("first")))
    body.add_tab(
        ActionTabSpec("Invalid", materialization_factory=lambda: object())
    )

    with pytest.raises(TypeError, match="must return ActionTabMaterialization"):
        body.materialize(1)

    assert not body.is_materialized(1)
    body.deleteLater()
    qapp.processEvents()


def test_user_activation_publishes_factory_failure_and_keeps_previous_tab(qapp):
    from PyQt6.QtWidgets import QLabel

    from pyqt_reactive.widgets.shared.action_tabbed_window_body import (
        ActionTabbedWindowBody,
        ActionTabSpec,
    )

    body = ActionTabbedWindowBody()
    failures = []
    body.tab_materialization_failed.connect(
        lambda index, error: failures.append((index, error))
    )
    body.add_tab(ActionTabSpec("First", content=QLabel("first")))
    body.add_tab(
        ActionTabSpec(
            "Broken",
            materialization_factory=lambda: (_ for _ in ()).throw(
                ValueError("deliberate factory failure")
            ),
        )
    )

    body.tab_bar.setCurrentIndex(1)
    qapp.processEvents()

    assert body.current_index() == 0
    assert body.content_stack.currentIndex() == 0
    assert body.widget(1) is None
    assert len(failures) == 1
    assert failures[0][0] == 1
    assert str(failures[0][1]) == "deliberate factory failure"


def test_programmatic_activation_publishes_factory_failure_once(qapp):
    """Programmatic selection delegates to the same single activation route."""
    from PyQt6.QtWidgets import QLabel

    from pyqt_reactive.widgets.shared.action_tabbed_window_body import (
        ActionTabbedWindowBody,
        ActionTabSpec,
    )

    body = ActionTabbedWindowBody()
    failures = []
    factory_calls = []
    body.tab_materialization_failed.connect(
        lambda index, error: failures.append((index, error))
    )
    body.add_tab(ActionTabSpec("First", content=QLabel("first")))

    def fail_factory():
        factory_calls.append(None)
        raise ValueError("deliberate programmatic factory failure")

    body.add_tab(
        ActionTabSpec(
            "Broken",
            materialization_factory=fail_factory,
        )
    )

    body.set_current_index(1)
    qapp.processEvents()

    assert body.current_index() == 0
    assert body.content_stack.currentIndex() == 0
    assert body.widget(1) is None
    assert len(factory_calls) == 1
    assert len(failures) == 1
    assert failures[0][0] == 1
    assert str(failures[0][1]) == "deliberate programmatic factory failure"


def test_invalid_lazy_actions_leave_placeholder_and_previous_tab_intact(qapp):
    from PyQt6.QtWidgets import QLabel

    from pyqt_reactive.widgets.shared.action_tabbed_window_body import (
        ActionTabbedWindowBody,
        ActionTabMaterialization,
        ActionTabSpec,
    )

    body = ActionTabbedWindowBody()
    failures = []
    body.tab_materialization_failed.connect(
        lambda index, error: failures.append((index, error))
    )
    body.add_tab(ActionTabSpec("First", content=QLabel("first")))
    body.add_tab(
        ActionTabSpec(
            "Broken",
            materialization_factory=lambda: ActionTabMaterialization(
                QLabel("second"),
                object(),  # type: ignore[arg-type]
            ),
        )
    )

    body.tab_bar.setCurrentIndex(1)
    qapp.processEvents()

    assert body.current_index() == 0
    assert body.content_stack.currentIndex() == 0
    assert body.widget(1) is None
    assert len(failures) == 1
    assert "actions must be QWidget or None" in str(failures[0][1])


def test_tab_spec_rejects_ambiguous_content_authority(qapp):
    import pytest
    from PyQt6.QtWidgets import QLabel

    from pyqt_reactive.widgets.shared.action_tabbed_window_body import ActionTabSpec

    with pytest.raises(ValueError, match="exactly one"):
        ActionTabSpec("Missing")
    with pytest.raises(ValueError, match="exactly one"):
        ActionTabSpec(
            "Duplicate",
            content=QLabel("content"),
            materialization_factory=lambda: object(),
        )

    with pytest.raises(ValueError, match="Lazy tab actions belong"):
        ActionTabSpec(
            "Duplicate actions",
            actions=QLabel("actions"),
            materialization_factory=lambda: object(),
        )
