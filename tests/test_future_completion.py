"""Completion delivery follows native Qt receiver and future lifetimes."""

import gc
import threading
import weakref
from concurrent.futures import Future

from PyQt6 import sip
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread, Slot

from pyqt_reactive.core.future_completion import FutureCompletion


class Receiver(QObject):
    def __init__(self):
        super().__init__()
        self.deliveries = []

    @Slot(object)
    def receive(self, future):
        self.deliveries.append((future, QThread.currentThread()))


def destroy(receiver):
    receiver.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(receiver)


def test_completion_after_receiver_destruction_preserves_other_subscribers(qapp):
    future = Future()
    destroyed = Receiver()
    surviving = Receiver()
    FutureCompletion(future, destroyed.receive)
    FutureCompletion(future, surviving.receive)
    destroy(destroyed)
    gc.collect()

    future.set_result(42)
    qapp.processEvents()

    assert destroyed.deliveries == []
    assert surviving.deliveries == [(future, qapp.thread())]
    assert future.result() == 42


def test_worker_completion_delivers_on_receiver_thread(qapp, qtbot):
    future = Future()
    receiver = Receiver()
    FutureCompletion(future, receiver.receive)

    worker = threading.Thread(target=future.set_result, args=(42,))
    worker.start()
    worker.join(timeout=2)
    assert not worker.is_alive()
    qtbot.waitUntil(lambda: len(receiver.deliveries) == 1)

    assert receiver.deliveries == [(future, qapp.thread())]


def test_completed_future_is_delivered_and_does_not_own_receiver(qapp):
    future = Future()
    future.set_result(42)
    receiver = Receiver()
    reference = weakref.ref(receiver)
    FutureCompletion(future, receiver.receive)
    assert receiver.deliveries == [(future, qapp.thread())]

    destroy(receiver)
    del receiver
    gc.collect()

    assert reference() is None


def test_cancelled_future_preserves_cancellation_for_receiver(qapp):
    future = Future()
    receiver = Receiver()
    FutureCompletion(future, receiver.receive)
    assert future.cancel()
    assert receiver.deliveries == [(future, qapp.thread())]
    assert receiver.deliveries[0][0].cancelled()
