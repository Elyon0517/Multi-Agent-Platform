from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator, Callable

from agentlab.core.schemas import Event


class Subscription(AsyncIterator[Event]):
    def __init__(self, queue: asyncio.Queue[Event], close: Callable[[], None]) -> None:
        self.queue, self.close = queue, close

    async def __anext__(self) -> Event:
        return await self.queue.get()

    async def aclose(self) -> None:
        self.close()


class InProcessEventBus:
    def __init__(self) -> None:
        self.listeners: list[Callable[[Event], None]] = []
        self._subs: dict[str, set[asyncio.Queue[Event]]] = defaultdict(set)

    def publish(self, event: Event) -> None:
        for listener in self.listeners:
            listener(event)
        for q in list(self._subs[event.run_id]) + list(self._subs["*"]):
            q.put_nowait(event)

    def subscribe(self, run_id: str) -> Subscription:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subs[run_id].add(queue)
        return Subscription(queue, lambda: self._subs[run_id].discard(queue))
