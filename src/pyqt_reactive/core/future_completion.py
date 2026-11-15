"""Future-owned completion delivery through Qt receiver lifetimes."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from typing import Generic, TypeVar

from PySide6.QtCore import QObject, Signal

ResultT = TypeVar("ResultT")


class FutureCompletion(QObject, Generic[ResultT]):
    """Deliver a future to a Qt slot without retaining a widget-owned signal.

    The future retains this unparented relay until its callbacks are released.
    Qt owns receiver disconnection: a decorated QObject slot is disconnected
    when that receiver is destroyed, without cancelling a shared operation.
    """

    completed = Signal(object)

    def __init__(
        self,
        future: Future[ResultT],
        receiver: Callable[[Future[ResultT]], None],
    ) -> None:
        super().__init__()
        self.completed.connect(receiver)
        future.add_done_callback(self._complete)

    def _complete(self, future: Future[ResultT]) -> None:
        self.completed.emit(future)
