from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel

from agentlab.core.ports import RunContext
from agentlab.core.schemas import AgentInput, AgentResult, Usage

T = TypeVar("T", bound=BaseModel)

Script = Callable[[AgentInput], BaseModel]


class FakeRuntime:
    def __init__(self, scripts: dict[str, Script], cost_cents_per_call: float = 0.1) -> None:
        self._scripts = scripts
        self._cost = cost_cents_per_call
        self.calls: list[tuple[str, int]] = []
        self.inputs: list[tuple[str, AgentInput]] = []

    async def run_agent(self, role: str, inp: AgentInput, output_type: type[T], ctx: RunContext) -> AgentResult[T]:
        ctx.check_budget(self._cost)
        self.calls.append((role, inp.iteration))
        self.inputs.append((role, inp))
        result: BaseModel
        if role == "supervisor":
            from agentlab.core.project_config import Binding, Dispatch

            available = list(inp.context["available_models"])
            result = Dispatch(
                assignments={
                    r: Binding(
                        alias=(
                            inp.context.get("default_aliases", {}).get(r)
                            or ("strong" if "strong" in available else available[0])
                        ),
                        task=f"Perform {r} for: {inp.goal}",
                    )
                    for r in inp.context["roles"]
                }
            )
        else:
            result = self._scripts[role](inp)
        out = output_type.model_validate(result.model_dump())
        usage = Usage(tokens_in=100, tokens_out=50, cost_cents=self._cost).for_call(role, "fake", "fake")
        return AgentResult[output_type](  # type: ignore[valid-type]
            role=role,
            output=out,
            alias="fake",
            model="fake",
            usage=usage,
            routing_reason="fake",
        )

    async def run_parallel(
        self, inputs: dict[str, AgentInput], output_type: type[T], ctx: RunContext
    ) -> list[AgentResult[T]]:
        return list(await asyncio.gather(*(self.run_agent(r, i, output_type, ctx) for r, i in inputs.items())))
