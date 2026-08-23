"""Owned dispatch of callable work onto the Qt application thread."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Generic, TypeVar, cast

from PyQt6.QtCore import QCoreApplication, QObject, Qt, QThread, pyqtSignal

ResultT = TypeVar("ResultT")


class UiThreadDispatchError(RuntimeError):
    """Raised when a UI-thread operation cannot be dispatched."""


class UiThreadDispatcherClosedError(UiThreadDispatchError):
    """Raised when dispatch is requested after shutdown begins."""


class UiThreadDispatchTimeoutError(TimeoutError):
    """Raised when a queued UI-thread operation does not begin in time."""


class _UiThreadCall(Generic[ResultT]):
    """One callable owned by a dispatcher until execution or cancellation."""

    def __init__(
        self,
        callback: Callable[[], ResultT],
        retire: Callable[[_UiThreadCall[ResultT]], None],
    ) -> None:
        self._callback = callback
        self._retire = retire
        self._lock = threading.Lock()
        self._started = False
        self._finished = False
        self.done = threading.Event()
        self.result: ResultT | None = None
        self.error: BaseException | None = None

    def run(self) -> None:
        with self._lock:
            if self._finished:
                return
            self._started = True
        try:
            result = self._callback()
        except BaseException as error:
            self._finish(error=error)
        else:
            self._finish(result=result)

    def cancel(self, error: BaseException) -> bool:
        with self._lock:
            if self._started or self._finished:
                return False
            self._finished = True
            self.error = error
        self._complete()
        return True

    def _finish(
        self,
        *,
        result: ResultT | None = None,
        error: BaseException | None = None,
    ) -> None:
        with self._lock:
            if self._finished:
                return
            self._finished = True
            self.result = result
            self.error = error
        self._complete()

    def _complete(self) -> None:
        self.done.set()
        self._retire(self)


class _UiThreadCallProxy(QObject):
    call_requested = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.call_requested.connect(
            self._execute,
            type=Qt.ConnectionType.QueuedConnection,
        )

    def _execute(self, call: _UiThreadCall) -> None:
        call.run()


class UiThreadDispatcher:
    """Own every callable queued onto the Qt application thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._closed = False
        self._calls: set[_UiThreadCall] = set()
        self._proxy: _UiThreadCallProxy | None = None
        application = QCoreApplication.instance()
        if application is not None:
            self._proxy = _UiThreadCallProxy()
            self._proxy.moveToThread(application.thread())

    def close(self) -> None:
        """Reject new work and cancel callbacks which have not begun."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            calls = tuple(self._calls)
        for call in calls:
            call.cancel(
                UiThreadDispatcherClosedError("UI dispatcher is shutting down.")
            )

    def call(
        self,
        callback: Callable[[], ResultT],
        *,
        timeout_ms: int = 5000,
    ) -> ResultT:
        """Run on the Qt thread and return its one authoritative outcome."""

        if self._is_ui_thread():
            self._require_open()
            return callback()
        if self._proxy is None:
            raise UiThreadDispatchError("No Qt application is available for UI dispatch.")

        call = self._register(callback)
        self._proxy.call_requested.emit(call)
        if not call.done.wait(timeout_ms / 1000):
            timeout = UiThreadDispatchTimeoutError(
                "Timed out waiting for UI thread dispatch."
            )
            if call.cancel(timeout):
                raise timeout
            call.done.wait()
        if call.error is not None:
            raise call.error
        return cast(ResultT, call.result)

    def post(self, callback: Callable[[], None]) -> None:
        """Queue work on the Qt thread without waiting for its result."""

        if self._proxy is None:
            if self._is_ui_thread():
                self._require_open()
                callback()
                return
            raise UiThreadDispatchError("No Qt application is available for UI dispatch.")
        self._proxy.call_requested.emit(self._register(callback))

    def _register(
        self,
        callback: Callable[[], ResultT],
    ) -> _UiThreadCall[ResultT]:
        with self._lock:
            if self._closed:
                raise UiThreadDispatcherClosedError(
                    "UI dispatcher is shutting down."
                )
            call = _UiThreadCall(callback, self._retire)
            self._calls.add(call)
            return call

    def _retire(self, call: _UiThreadCall) -> None:
        with self._lock:
            self._calls.discard(call)

    def _require_open(self) -> None:
        with self._lock:
            if self._closed:
                raise UiThreadDispatcherClosedError(
                    "UI dispatcher is shutting down."
                )

    @staticmethod
    def _is_ui_thread() -> bool:
        application = QCoreApplication.instance()
        if application is None:
            return True
        return QThread.currentThread() == application.thread()
