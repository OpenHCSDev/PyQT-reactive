"""Owned dispatch of callable work onto the Qt application thread."""

from __future__ import annotations

from typing import cast

from formbridge.services.main_thread_dispatch import (
    DispatchedCall,
    MainThreadDispatchError,
    MainThreadDispatcher,
)
from PyQt6.QtCore import QCoreApplication, QObject, Qt, QThread, pyqtSignal


class _UiThreadCallProxy(QObject):
    call_requested = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.call_requested.connect(
            self._execute,
            type=Qt.ConnectionType.QueuedConnection,
        )

    def _execute(self, call: DispatchedCall) -> None:
        call.run()


class UiThreadDispatcher(MainThreadDispatcher):
    """Deliver dispatched calls through the Qt application's event loop."""

    def __init__(self) -> None:
        super().__init__()
        self._proxy: _UiThreadCallProxy | None = None
        application = QCoreApplication.instance()
        if application is not None:
            self._proxy = _UiThreadCallProxy()
            self._proxy.moveToThread(application.thread())

    def _is_owner_thread(self) -> bool:
        application = QCoreApplication.instance()
        if application is None:
            return True
        return QThread.currentThread() == application.thread()

    def _can_deliver(self) -> bool:
        return self._proxy is not None

    def _deliver(self, call: DispatchedCall) -> None:
        cast(_UiThreadCallProxy, self._proxy).call_requested.emit(call)

    def _undeliverable_error(self) -> MainThreadDispatchError:
        return MainThreadDispatchError("No Qt application is available for UI dispatch.")
