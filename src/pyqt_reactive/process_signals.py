"""Process-signal integration for Qt application event loops."""

from __future__ import annotations

import signal
from collections.abc import Iterable
from types import FrameType
from typing import Any

from PyQt6.QtCore import QCoreApplication, QObject, QTimer


class QtProcessSignalRelay(QObject):
    """Route process termination signals through the Qt event loop.

    Python otherwise may raise ``KeyboardInterrupt`` inside an arbitrary Qt
    callback, where the binding reports it as an unhandled callback exception
    and leaves the application running.  The timer gives the interpreter a
    regular signal-processing opportunity; the installed handler exits Qt with
    the conventional process signal status.
    """

    def __init__(
        self,
        application: QCoreApplication,
        *,
        poll_interval_ms: int = 100,
        handled_signals: Iterable[signal.Signals] = (
            signal.SIGINT,
            signal.SIGTERM,
        ),
    ) -> None:
        super().__init__(application)
        if poll_interval_ms <= 0:
            raise ValueError("Signal poll interval must be positive.")

        self._application = application
        self._handler = self._handle_signal
        self._previous_handlers: dict[signal.Signals, Any] = {}
        for signal_number in handled_signals:
            self._previous_handlers[signal_number] = signal.getsignal(signal_number)
            signal.signal(signal_number, self._handler)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_python_signals)
        self._poll_timer.start(poll_interval_ms)
        application.aboutToQuit.connect(self.close)

    def close(self) -> None:
        """Stop polling and restore only the handlers this relay still owns."""

        self._poll_timer.stop()
        for signal_number, previous_handler in self._previous_handlers.items():
            if signal.getsignal(signal_number) is self._handler:
                signal.signal(signal_number, previous_handler)
        self._previous_handlers.clear()

    def _poll_python_signals(self) -> None:
        """Give Python a recurring bytecode boundary while Qt owns the thread."""

    def _handle_signal(
        self,
        signal_number: int,
        _frame: FrameType | None,
    ) -> None:
        self._application.exit(128 + signal_number)
