from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from agentlab.core.config import AppConfig
from agentlab.core.ports import RunContext
from agentlab.core.schemas import AgentInput, AgentResult

T = TypeVar("T", bound=BaseModel)


class AdkUnavailable(ImportError):
    pass


class AdkRuntime:
    def __init__(self, cfg: AppConfig, base_url: str, api_key: str) -> None:
        try:
            import google.adk  # noqa: F401
        except ImportError as e:
            raise AdkUnavailable("install with: uv sync --extra adk") from e
        self._cfg = cfg
        self._base_url = base_url
        self._api_key = api_key

    async def run_agent(
        self, role: str, inp: AgentInput, output_type: type[T], ctx: RunContext
    ) -> AgentResult[T]:
        raise NotImplementedError("P3: LlmAgent(LiteLlm(model=alias), output_schema, before_model_callback)")

    async def run_parallel(
        self, inputs: dict[str, AgentInput], output_type: type[T], ctx: RunContext
    ) -> list[AgentResult[T]]:
        raise NotImplementedError("P3: ParallelAgent(sub_agents=[...reviewers])")
