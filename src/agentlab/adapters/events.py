from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator

from agentlab.core.schemas import Event


class InProcessEventBus:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue[Event]]] = defaultdict(set)

    def publish(self, event: Event) -> None:
        for q in list(self._subs[event.run_id]) + list(self._subs["*"]):
            q.put_nowait(event)

    async def subscribe(self, run_id: str) -> AsyncIterator[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue()
        self._subs[run_id].add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subs[run_id].discard(q)
