from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator, Callable

from agentlab.core.schemas import Event


class Subscription(AsyncIterator[Event]):
    def __init__(self, queue: asyncio.Queue[Event | None], close: Callable[[], None]) -> None:
        self.queue, self.close = queue, close

    async def __anext__(self) -> Event:
        event = await self.queue.get()
        if event is None:
            raise StopAsyncIteration
        return event

    async def aclose(self) -> None:
        self.close()


class InProcessEventBus:
    def __init__(self) -> None:
        self.listeners: list[Callable[[Event], None]] = []
        self._subs: dict[str, set[asyncio.Queue[Event | None]]] = defaultdict(set)

    def publish(self, event: Event) -> None:
        for listener in self.listeners:
            listener(event)
        for q in list(self._subs.get(event.run_id, ())) + list(self._subs.get("*", ())):
            q.put_nowait(event)

    def subscribe(self, run_id: str) -> Subscription:
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        self._subs[run_id].add(queue)
        def close() -> None:
            subscribers = self._subs.get(run_id)
            if subscribers is not None:
                subscribers.discard(queue)
                if not subscribers:
                    self._subs.pop(run_id, None)
        return Subscription(queue, close)

    def forget(self, run_id: str) -> None:
        for queue in self._subs.pop(run_id, ()):
            queue.put_nowait(None)
