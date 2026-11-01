"""Route C: Google ADK runs each agent under the existing deterministic Driver. See docs/ADK_RUNTIME.md."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, TypeVar

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import Workflow
from google.genai import types
from pydantic import BaseModel, ConfigDict, ValidationError

from agentlab.adapters.runtime.adk.agents import agent_name, build_agent, kickoff
from agentlab.adapters.runtime.adk.model import AgentLabLlm, CallState
from agentlab.adapters.runtime.adk.tools import granted_tools
from agentlab.core.config import AppConfig
from agentlab.core.llm.attempt import ChatFn
from agentlab.core.llm.retry import LlmError, ParallelFailure, RetriesExhausted
from agentlab.core.llm.structured import CallPlan, StructuredCaller, render_user_message
from agentlab.core.ports import RunContext
from agentlab.core.routing import Override
from agentlab.core.schemas import AgentInput, AgentResult

T = TypeVar("T", bound=BaseModel)

APP = "agentlab"


class RoleAgent(BaseAgent):
    """One role inside an ADK invocation: AgentLab routing, alias fallback and output repair around LlmAgent
    attempts. Each alias attempt runs in its own branch, so a fallback starts from a clean history.

    Outcomes go to the shared `outcomes` map (ADK runs copies of workflow nodes). Errors are kept instead of
    raised: a failing node would stop the whole panel, while the Driver reuses the reviewers that did finish.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    caller: Any
    role: str
    inp: Any
    output_type: Any
    ctx: Any
    outcomes: Any  # dict[str, ...]; typed Any so pydantic shares it with node copies instead of copying it
    override: Any = None

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        caller: AdkCaller = self.caller
        try:
            plan = caller.begin(self.role, self.ctx, self.override)
            last: Exception | None = None
            for alias in plan.route.chain:
                output: list[Any] = []
                try:
                    async for event in caller.attempt(ctx, plan, self.role, alias, self.inp, self.output_type, output):
                        yield event
                except RetriesExhausted as e:
                    last = e
                    continue
                self.outcomes[self.role] = caller.finish(plan, self.role, alias, output[0], self.output_type)
                return
            assert last is not None
            raise last
        except Exception as e:
            self.outcomes[self.role] = e


class AdkCaller(StructuredCaller):
    """Routing and result accounting are inherited; every agent turn runs inside an ADK invocation."""

    async def call(
        self,
        role: str,
        inp: AgentInput,
        output_type: type[T],
        ctx: RunContext,
        override: Override | None = None,
    ) -> AgentResult[T]:
        outcomes: dict[str, Any] = {}
        await self._invoke(RoleAgent(name=agent_name(role), caller=self, role=role, inp=inp, output_type=output_type,
                                     ctx=ctx, outcomes=outcomes, override=override))
        if isinstance(outcomes[role], Exception):
            raise outcomes[role]
        return outcomes[role]  # type: ignore[no-any-return]

    async def panel(self, inputs: dict[str, AgentInput], output_type: type[T], ctx: RunContext) -> dict[str, Any]:
        """Fan the roles out from START in one ADK Workflow; returns each role's AgentResult or exception."""
        outcomes: dict[str, Any] = {}
        agents = tuple(RoleAgent(name=agent_name(role), caller=self, role=role, inp=inp, output_type=output_type,
                                 ctx=ctx, outcomes=outcomes) for role, inp in inputs.items())
        await self._invoke(Workflow(name="review_panel", edges=[("START", agents)]))
        return {role: outcomes[role] for role in inputs}

    async def _invoke(self, root: BaseAgent | Workflow) -> None:
        # The session is scratch space for one call; durable state lives in the Store and attempt records.
        sessions = InMemorySessionService()
        runner = (Runner(node=root, app_name=APP, session_service=sessions) if isinstance(root, Workflow)
                  else Runner(agent=root, app_name=APP, session_service=sessions))
        session = await runner.session_service.create_session(app_name=APP, user_id=APP)
        async for _ in runner.run_async(user_id=APP, session_id=session.id, new_message=kickoff()):
            pass

    async def attempt(
        self, ctx: InvocationContext, plan: CallPlan, role: str, alias: str, inp: AgentInput,
        output_type: type[T], output: list[Any],
    ) -> AsyncGenerator[Event, None]:
        """One alias: run the role's LlmAgent, validate its final text and repair in the same branch."""
        state = CallState()
        llm = AgentLabLlm.build(self._chat, self._cfg, plan.ctx, plan.log, state, role=role, alias=alias,
                                temperature=plan.route.temperature, output_schema=output_type.model_json_schema())
        agent = build_agent(role, llm, self._cfg.prompt(role), granted_tools(plan.ctx, role, state))
        branch = f"{ctx.branch or agent.name}.{alias}"
        scoped = ctx.model_copy(update={"branch": branch})
        message = render_user_message(inp)
        repairs = 0
        while repairs <= self._cfg.retry.structured_output_repair.max_repairs:
            yield Event(author="user", invocation_id=ctx.invocation_id, branch=branch,
                        content=types.Content(role="user", parts=[types.Part(text=message)]))
            text = ""
            async for event in agent.run_async(scoped):
                yield event
                if event.author == agent.name and event.content and not event.get_function_calls():
                    text = "".join(p.text for p in event.content.parts or [] if p.text and not p.thought) or text
            try:
                output.append(output_type.model_validate_json(text))
                return
            except ValidationError as e:
                repairs += 1
                plan.log.reasons.append("structured_output_invalid")
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
        """The review panel is one ADK Workflow fan-out; each reviewer keeps its own model, fallback and repair."""
        outcomes = await self._caller.panel(inputs, output_type, ctx)
        results = [o for o in outcomes.values() if not isinstance(o, Exception)]
        errors = [o for o in outcomes.values() if isinstance(o, Exception)]
        if errors:
            raise ParallelFailure(errors[0], results)
        return results
