"""ADK model adapter: every model call ADK makes goes through AgentLab's metered gateway call."""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

from google.adk.models import BaseLlm, LlmCapabilities
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import ConfigDict

from agentlab.core.config import AppConfig
from agentlab.core.llm.attempt import ChatFn, metered_call
from agentlab.core.llm.retry import AttemptLog, LlmError
from agentlab.core.ports import RunContext
from agentlab.core.schemas import Usage

# Wraps a non-object tool result, since ADK function responses must be objects.
VALUE_KEY = "_agentlab_value"


@dataclass
class CallState:
    """What ADK's types.Content cannot carry, keyed by tool call id, for one agent invocation."""

    arguments: dict[str, str] = field(default_factory=dict)
    provider_content: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)


def _system(request: LlmRequest) -> str:
    instruction = request.config.system_instruction
    if isinstance(instruction, types.Content):
        return "\n\n".join(p.text for p in instruction.parts or [] if p.text)
    return instruction if isinstance(instruction, str) else ""


def to_messages(contents: list[types.Content], state: CallState) -> list[dict[str, Any]]:
    """ADK contents → the OpenAI-style messages the gateway chat functions take."""
    messages: list[dict[str, Any]] = []
    for content in contents:
        parts = [p for p in content.parts or [] if not p.thought]
        text = "".join(p.text for p in parts if p.text)
        calls = [p.function_call for p in parts if p.function_call]
        responses = [p.function_response for p in parts if p.function_response]
        if content.role == "model":
            message: dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                message["tool_calls"] = [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.name, "arguments": state.arguments.get(c.id or "", json.dumps(c.args))}}
                    for c in calls
                ]
                if provider := state.provider_content.get(calls[0].id or ""):
                    message["_anthropic_content"] = provider
            messages.append(message)
            continue
        for r in responses:
            value = r.response or {}
            value = value[VALUE_KEY] if set(value) == {VALUE_KEY} else value
            messages.append({"role": "tool", "tool_call_id": r.id, "content": json.dumps(value, ensure_ascii=False)})
        if text:
            messages.append({"role": "user", "content": text})
    return messages


class AgentLabLlm(BaseLlm):
    """One role on one alias. ADK owns the agent loop; AgentLab owns retries, budget and accounting."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    chat: Any
    cfg: Any
    ctx: Any
    log: Any
    state: Any
    role: str
    alias: str
    temperature: float
    output_schema: dict[str, Any]

    @classmethod
    def build(cls, chat: ChatFn, cfg: AppConfig, ctx: RunContext, log: AttemptLog, state: CallState, *,
              role: str, alias: str, temperature: float, output_schema: dict[str, Any]) -> AgentLabLlm:
        return cls(model=cfg.models.aliases[alias].model, chat=chat, cfg=cfg, ctx=ctx, log=log, state=state,
                   role=role, alias=alias, temperature=temperature, output_schema=output_schema)

    @property
    def capabilities(self) -> LlmCapabilities:
        # The output schema reaches the gateway through `schema`, never through ADK's output_schema.
        return LlmCapabilities(output_schema_and_tools=False)

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        ctx: RunContext = self.ctx
        completion, charged = await metered_call(
            self.chat, self.cfg, ctx, self.log,
            role=self.role, alias=self.alias, system=_system(llm_request),
            messages=to_messages(llm_request.contents, self.state), schema=self.output_schema,
            temperature=self.temperature,
        )
        usage = self.state.usage
        self.state.usage = Usage(tokens_in=usage.tokens_in + charged.tokens_in, tokens_out=usage.tokens_out
                                 + charged.tokens_out, cost_cents=usage.cost_cents + charged.cost_cents)
        parts = [types.Part(text=completion.text)] if completion.text else []
        if completion.tool_calls:
            if not ctx.tool_specs:
                raise LlmError("unexpected_tool_calls")
            if not ctx.execute_tool:
                raise LlmError("tools_unavailable")
            for call in completion.tool_calls:
                function = call["function"]
                self.state.arguments[call["id"]] = function["arguments"]
                try:
                    args = json.loads(function["arguments"])
                except ValueError:
                    args = None
                parts.append(types.Part(function_call=types.FunctionCall(
                    id=call["id"], name=function["name"], args=args if isinstance(args, dict) else {},
                )))
            if completion.provider_content:
                self.state.provider_content[completion.tool_calls[0]["id"]] = completion.provider_content
        yield LlmResponse(content=types.Content(role="model", parts=parts), turn_complete=True)
