"""Lifecycle tests for owned Qt-thread dispatch."""

from __future__ import annotations

import threading
import time

import pytest

from pyqt_reactive.services.ui_thread_dispatch import (
    UiThreadDispatcher,
    UiThreadDispatcherClosedError,
    UiThreadDispatchTimeoutError,
)


def test_close_cancels_a_posted_callback_before_qt_executes_it(qapp) -> None:
    dispatcher = UiThreadDispatcher()
    calls: list[str] = []

    dispatcher.post(lambda: calls.append("late"))
    dispatcher.close()
    qapp.processEvents()

    assert calls == []
    with pytest.raises(UiThreadDispatcherClosedError):
        dispatcher.post(lambda: None)


def test_call_timeout_cancels_callback_still_queued_for_qt(qapp) -> None:
    dispatcher = UiThreadDispatcher()
    calls: list[str] = []
    errors: list[BaseException] = []

    def call_from_worker() -> None:
        try:
            dispatcher.call(lambda: calls.append("late"), timeout_ms=10)
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=call_from_worker)
    worker.start()
    worker.join(timeout=1.0)
    qapp.processEvents()

    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], UiThreadDispatchTimeoutError)
    assert calls == []


def test_close_unblocks_worker_waiting_for_queued_call(qapp) -> None:
    dispatcher = UiThreadDispatcher()
    errors: list[BaseException] = []
    call_started = threading.Event()

    def call_from_worker() -> None:
        call_started.set()
        try:
            dispatcher.call(lambda: None, timeout_ms=5000)
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=call_from_worker)
    worker.start()
    assert call_started.wait(timeout=1.0)
    dispatcher.close()
    worker.join(timeout=1.0)
    qapp.processEvents()

    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], UiThreadDispatcherClosedError)


def test_call_waits_for_atomic_callback_that_started_before_timeout(qapp, qtbot) -> None:
    dispatcher = UiThreadDispatcher()
    callback_started = threading.Event()
    release_callback = threading.Event()
    outcomes = []
    admission_timeout_ms = 500

    def slow_callback() -> str:
        callback_started.set()
        release_callback.wait(timeout=1.0)
        return "committed"

    worker = threading.Thread(
        target=lambda: outcomes.append(
            dispatcher.call(slow_callback, timeout_ms=admission_timeout_ms)
        )
    )

    def release_after_admission_timeout() -> None:
        assert callback_started.wait(timeout=1.0)
        time.sleep((admission_timeout_ms + 50) / 1000)
        release_callback.set()

    releaser = threading.Thread(target=release_after_admission_timeout)
    releaser.start()
    assert dispatcher._proxy is not None
    with qtbot.waitSignal(dispatcher._proxy.call_requested, timeout=1000):
        worker.start()
    qapp.processEvents()
    worker.join(timeout=1.0)
    releaser.join(timeout=1.0)

    assert not worker.is_alive()
    assert outcomes == ["committed"]
