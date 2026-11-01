"""Route C: Google ADK runs each agent under the existing deterministic Driver. See docs/ADK_RUNTIME.md."""
from __future__ import annotations

import asyncio
from typing import TypeVar

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, ValidationError

from agentlab.adapters.runtime.adk.agents import agent_name, build_agent
from agentlab.adapters.runtime.adk.model import AgentLabLlm, CallState
from agentlab.adapters.runtime.adk.tools import granted_tools
from agentlab.core.config import AppConfig
from agentlab.core.llm.attempt import ChatFn
from agentlab.core.llm.retry import AttemptLog, LlmError, NonRetryable, ParallelFailure
from agentlab.core.llm.structured import StructuredCaller, render_user_message
from agentlab.core.ports import RunContext
from agentlab.core.routing import Route
from agentlab.core.schemas import AgentInput, AgentResult, Usage

T = TypeVar("T", bound=BaseModel)

APP = "agentlab"


class AdkCaller(StructuredCaller):
    """Routing, alias fallback and result accounting are inherited; one alias attempt runs as an ADK agent."""

    async def _call_alias(
        self,
        route: Route,
        alias: str,
        role: str,
        inp: AgentInput,
        output_type: type[T],
        ctx: RunContext,
        log: AttemptLog,
    ) -> tuple[T, Usage]:
        state = CallState()
        llm = AgentLabLlm.build(self._chat, self._cfg, ctx, log, state, role=role, alias=alias,
                                temperature=route.temperature, output_schema=output_type.model_json_schema())
        agent = build_agent(role, llm, self._cfg.prompt(role), granted_tools(ctx, role, state))
        # The session is scratch space for one attempt; durable state lives in the Store and attempt records.
        runner = Runner(agent=agent, app_name=APP, session_service=InMemorySessionService())
        session = await runner.session_service.create_session(app_name=APP, user_id=APP)
        message = render_user_message(inp)
        repairs = 0
        while repairs <= self._cfg.retry.structured_output_repair.max_repairs:
            text = ""
            async for event in runner.run_async(
                user_id=APP, session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text=message)]),
            ):
                if event.author == agent_name(role) and event.content and not event.get_function_calls():
                    text = "".join(p.text for p in event.content.parts or [] if p.text and not p.thought) or text
            try:
                return output_type.model_validate_json(text), state.usage
            except ValidationError as e:
                repairs += 1
                log.reasons.append("structured_output_invalid")
                message = f"Your output failed validation. Fix and resend JSON only:\n{e}"
        raise LlmError(f"{role}: structured output invalid after repairs")


class AdkRuntime:
    def __init__(self, cfg: AppConfig, chat: ChatFn) -> None:
        self._caller = AdkCaller(cfg, chat)

    async def run_agent(self, role: str, inp: AgentInput, output_type: type[T], ctx: RunContext) -> AgentResult[T]:
        return await self._caller.call(role, inp, output_type, ctx)

    async def run_parallel(
        self, inputs: dict[str, AgentInput], output_type: type[T], ctx: RunContext
    ) -> list[AgentResult[T]]:
        # P3 replaces this with an ADK ParallelAgent review panel.
        outcomes = await asyncio.gather(
            *(self.run_agent(r, i, output_type, ctx) for r, i in inputs.items()), return_exceptions=True
        )
        results = [result for result in outcomes if not isinstance(result, BaseException)]
        for outcome in outcomes:
            if isinstance(outcome, asyncio.CancelledError):
                raise ParallelFailure(NonRetryable("agent_cancelled"), results)
            if isinstance(outcome, BaseException) and not isinstance(outcome, Exception):
                raise outcome
        errors = [result for result in outcomes if isinstance(result, Exception)]
        if errors:
            raise ParallelFailure(errors[0], results)
        return results
