"""Deliveries consumed on the thread of the QObject that receives them, one at a time, in order.

The receiver is a native capability of the actual widget or object, not a manager beside it
(plans/formgen-comms-backends 02:140). A delivery may be posted from any thread: its
QtDeliveryEvent carries it to the receiver's own thread, where it joins the receiver's queue.
One drain task awaits each delivery before taking the next, so a handler that awaits sees no
later delivery overtake it; separate receivers drain separately, so one receiver waiting on
another cannot deadlock it. Deliveries are never replaced or merged: native input between two
deliveries reaches no barrier here, so nothing may coalesce across it (02:138).
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable

from PySide6.QtCore import QCoreApplication, QEvent

Delivery = Callable[[], Awaitable[None]]


class QtDeliveryEvent(QEvent):
    """The native wake that carries one delivery to its receiver's thread."""

    TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(self, delivery: Delivery) -> None:
        super().__init__(self.TYPE)
        self.delivery = delivery


class QtDeliveryReceiver:
    """Mixed into the QObject that receives deliveries, before its Qt base.

    The queue holds the delivery being consumed at its head until it finishes, so the drain
    runs exactly while the queue is not empty. A failed delivery goes to delivery_failed and
    the drain continues. Qt discards events still posted to a deleted receiver;
    close_deliveries drops what is queued and cancels the drain.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.deliveries: deque[Delivery] = deque()

    def deliver(self, delivery: Delivery) -> None:
        """Queue a delivery from any thread."""
        QCoreApplication.postEvent(self, QtDeliveryEvent(delivery))

    def event(self, event: QEvent) -> bool:
        if event.type() != QtDeliveryEvent.TYPE:
            return super().event(event)
        self.deliveries.append(event.delivery)
        if len(self.deliveries) == 1:
            self.drain = asyncio.ensure_future(self.drain_deliveries())
        return True

    async def drain_deliveries(self) -> None:
        while self.deliveries:
            try:
                await self.deliveries[0]()
            except Exception as error:
                self.delivery_failed(error)
            self.deliveries.popleft()

    def delivery_failed(self, error: Exception) -> None:
        """Report a delivery that raised through the receiver's failure owner; it must not
        raise, since the drain continues with the next delivery."""
        raise NotImplementedError

    def close_deliveries(self) -> None:
        """Drop every queued delivery and cancel the one being consumed."""
        if self.deliveries:
            self.drain.cancel()
        self.deliveries.clear()
