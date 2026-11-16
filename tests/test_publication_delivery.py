"""A receiver consumes its deliveries on its own thread, one at a time, in order."""

from __future__ import annotations

import asyncio
import threading

from PySide6.QtCore import QCoreApplication, QObject

from pyqt_reactive.services.publication_delivery import QtDeliveryReceiver


class Receiver(QtDeliveryReceiver, QObject):
    def __init__(self) -> None:
        super().__init__()
        self.failures: list[Exception] = []

    def delivery_failed(self, error: Exception) -> None:
        self.failures.append(error)


async def settle() -> None:
    for _ in range(5):
        QCoreApplication.sendPostedEvents()
        await asyncio.sleep(0)


def test_receiver_drains_in_order_and_survives_a_failed_delivery(qapp) -> None:
    async def scenario() -> None:
        receiver = Receiver()
        seen: list[str] = []
        gate = asyncio.Event()
        broken = RuntimeError("broken delivery")

        async def slow() -> None:
            seen.append("slow started")
            await gate.wait()
            seen.append("slow finished")

        async def failing() -> None:
            raise broken

        async def last() -> None:
            seen.append("last")

        receiver.deliver(slow)
        worker = threading.Thread(target=receiver.deliver, args=(failing,))
        worker.start()
        worker.join()
        receiver.deliver(last)
        await settle()
        assert seen == ["slow started"]
        gate.set()
        await settle()
        assert seen == ["slow started", "slow finished", "last"]
        assert receiver.failures == [broken]
        assert not receiver.deliveries

    asyncio.run(scenario())


def test_close_drops_queued_deliveries_and_cancels_the_running_one(qapp) -> None:
    async def scenario() -> None:
        receiver = Receiver()
        seen: list[str] = []

        async def waits() -> None:
            seen.append("started")
            await asyncio.Event().wait()

        async def never() -> None:
            seen.append("never")

        receiver.deliver(waits)
        receiver.deliver(never)
        await settle()
        receiver.close_deliveries()
        await settle()
        assert seen == ["started"]
        assert receiver.drain.cancelled()
        assert not receiver.deliveries

    asyncio.run(scenario())
