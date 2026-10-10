from __future__ import annotations

from typing import Any, Protocol

from agentlab.core.schemas import AgentInput, Run, Verdict


class RunHooks(Protocol):
    async def context_for(self, run: Run, role: str, inp: AgentInput) -> dict[str, Any]: ...

    async def after_reviews(self, run: Run, verdicts: list[Verdict]) -> None: ...

    async def on_finished(self, run: Run) -> None: ...


class NoHooks:
    async def context_for(self, run: Run, role: str, inp: AgentInput) -> dict[str, Any]:
        return {}

    async def after_reviews(self, run: Run, verdicts: list[Verdict]) -> None:
        return None

    async def on_finished(self, run: Run) -> None:
        return None
