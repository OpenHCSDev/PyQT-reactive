"""Callbacks bounded by their target QObject's native lifetime: once later, or on an interval."""

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Slot


class OwnedCallback(QTimer):
    """A callback timer parented to its owner, so the owner's destruction cancels it."""

    def __init__(self, owner: QObject, interval_ms: int, callback: Callable[[], None]) -> None:
        super().__init__(owner)
        self._callback = callback
        self.timeout.connect(self._invoke)
        self.start(interval_ms)

    @Slot()
    def _invoke(self) -> None:
        self._callback()


class DeferredCallback(OwnedCallback):
    """Deliver one callback while its owner exists, then retire the timer."""

    def __init__(self, owner: QObject, delay_ms: int, callback: Callable[[], None]) -> None:
        super().__init__(owner, delay_ms, callback)
        self.setSingleShot(True)

    @Slot()
    def _invoke(self) -> None:
        # The callback may destroy the owner, including this child timer.
        self.deleteLater()
        super()._invoke()


class RepeatingCallback(OwnedCallback):
    """Deliver a callback every interval while its owner exists; stop() ends it."""
