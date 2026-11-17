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
    """Deliver one callback while its owner exists.

    The owner is the only owner: ``setSingleShot(True)`` stops the timer after one delivery,
    and the owner's destruction cascade deletes the timer. The timer never schedules its own
    deletion from inside the slot, because that queues a ``DeferredDelete`` against a child
    whose parent may be torn down in the same event-loop pass. Qt drops a posted delete when
    its receiver's parent dies first, but PySide's wrapper still runs ``QTimer::~QTimer`` on
    freed property-binding storage, which segfaulted the suite at
    tests/test_widget_tree_projection.py::test_nominal_widget_projectors_own_indexed_selection
    (bus 2f8b474c7a7c). One owner, no race.
    """

    def __init__(self, owner: QObject, delay_ms: int, callback: Callable[[], None]) -> None:
        super().__init__(owner, delay_ms, callback)
        self.setSingleShot(True)


class RepeatingCallback(OwnedCallback):
    """Deliver a callback every interval while its owner exists; stop() ends it."""
