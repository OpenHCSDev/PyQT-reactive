"""Real QObject lifetimes bound queued widget and row actions."""

import gc
import weakref

import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QObject
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QComboBox, QGroupBox, QListView, QPushButton

from pyqt_reactive.core.deferred_callback import DeferredCallback, RepeatingCallback
from pyqt_reactive.services.widget_tree_projection import (
    DEFAULT_WIDGET_DESCRIPTOR_PROJECTOR_REGISTRY,
    SelectItemAction,
    WidgetActionKind,
)


def destroy(owner):
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(owner)


def test_deferred_callback_runs_once_and_retires(qapp):
    owner = QObject()
    calls = []
    timer = DeferredCallback(owner, 0, lambda: calls.append(owner))
    assert timer.parent() is owner
    assert calls == []
    qapp.processEvents()
    assert calls == [owner]
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(timer)
    assert owner.children() == []
    qapp.processEvents()
    assert calls == [owner]
    destroy(owner)


def test_repeating_callback_runs_until_stopped_or_owner_destroyed(qapp):
    owner = QObject()
    calls = []
    timer = RepeatingCallback(owner, 0, lambda: calls.append("tick"))
    assert timer.parent() is owner
    assert timer.isActive() and not timer.isSingleShot()
    qapp.processEvents()
    qapp.processEvents()
    assert len(calls) >= 2
    timer.stop()
    stopped = len(calls)
    qapp.processEvents()
    assert len(calls) == stopped
    timer.start()
    destroy(owner)
    assert not shiboken6.isValid(timer)
    qapp.processEvents()
    assert len(calls) == stopped


def test_owner_destruction_cancels_only_its_callbacks(qapp):
    cancelled, surviving = QObject(), QObject()
    calls = []
    timer = DeferredCallback(cancelled, 0, lambda: calls.append("cancelled"))
    DeferredCallback(surviving, 0, lambda: calls.append("surviving"))
    destroy(cancelled)
    assert not shiboken6.isValid(timer)
    qapp.processEvents()
    assert calls == ["surviving"]
    destroy(surviving)


def test_callback_can_destroy_its_owner(qapp):
    owner = QObject()
    timer = DeferredCallback(owner, 0, lambda: shiboken6.delete(owner))
    qapp.processEvents()
    assert not shiboken6.isValid(owner)
    assert not shiboken6.isValid(timer)


def test_cancelled_callback_does_not_retain_target(qapp):
    owner = QObject()
    reference = weakref.ref(owner)
    DeferredCallback(owner, 0, lambda owner=owner: owner.objectName())
    destroy(owner)
    del owner
    gc.collect()
    qapp.processEvents()
    assert reference() is None


@pytest.mark.parametrize(
    "widget_type, action, target_index",
    [
        (QPushButton, WidgetActionKind.BUTTON, None),
        (QComboBox, WidgetActionKind.CHOICE, 1),
        (QGroupBox, WidgetActionKind.CHECKABLE, None),
    ],
)
def test_projected_actions_are_cancelled_with_target(qapp, widget_type, action, target_index):
    widget = widget_type()
    if isinstance(widget, QComboBox):
        widget.addItems(["first", "second"])
    if isinstance(widget, QGroupBox):
        widget.setCheckable(True)
    projector = DEFAULT_WIDGET_DESCRIPTOR_PROJECTOR_REGISTRY.projector_for(widget)
    projector.invoke_action(widget, action, target_index=target_index)
    timers = widget.findChildren(DeferredCallback)
    assert len(timers) == 1
    destroy(widget)
    assert not shiboken6.isValid(timers[0])
    qapp.processEvents()


def row_view():
    view = QListView()
    model = QStandardItemModel(view)
    model.appendRow(QStandardItem("Z target"))
    model.appendRow(QStandardItem("A other"))
    view.setModel(model)
    return view, model


def test_deferred_item_action_survives_row_reordering(qapp):
    view, model = row_view()
    SelectItemAction().defer(view, model.index(0, 0))
    model.sort(0)
    assert model.index(0, 0).data() == "A other"
    qapp.processEvents()
    assert view.currentIndex().data() == "Z target"
    assert view.currentIndex().row() == 1
    destroy(view)


def test_deferred_item_action_cancels_when_target_row_is_removed(qapp):
    view, model = row_view()
    SelectItemAction().defer(view, model.index(0, 0))
    model.removeRow(0)
    qapp.processEvents()
    assert model.index(0, 0).data() == "A other"
    assert not view.currentIndex().isValid()
    destroy(view)


def test_deferred_item_action_cancels_when_view_changes_model(qapp):
    view, model = row_view()
    SelectItemAction().defer(view, model.index(0, 0))
    replacement = QStandardItemModel(view)
    replacement.appendRow(QStandardItem("Replacement"))
    view.setModel(replacement)
    qapp.processEvents()
    assert not view.currentIndex().isValid()
    destroy(view)


def test_deferred_item_action_cancels_when_view_is_destroyed(qapp):
    view, model = row_view()
    SelectItemAction().defer(view, model.index(0, 0))
    destroy(view)
    qapp.processEvents()
