from __future__ import annotations

import json
import time
from dataclasses import replace
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from agentlab.core.budget import BudgetExceeded
from agentlab.core.config import AppConfig
from agentlab.core.llm.attempt import ChatFn, Completion, metered_call
from agentlab.core.llm.retry import AttemptLog, LlmError, RetriesExhausted
from agentlab.core.monitor import UsageAccumulator
from agentlab.core.ports import RunContext
from agentlab.core.routing import Override, Route, Router
from agentlab.core.schemas import AgentInput, AgentResult, Usage

__all__ = ["ChatFn", "Completion", "StructuredCaller", "render_user_message"]

T = TypeVar("T", bound=BaseModel)


def render_user_message(inp: AgentInput) -> str:
    return inp.model_dump_json(exclude_none=True, exclude_defaults=True, indent=1)


class StructuredCaller:
    def __init__(self, cfg: AppConfig, chat: ChatFn) -> None:
        self._cfg = cfg
        self._router = Router(cfg)
        self._chat = chat

    async def call(
        self,
        role: str,
        inp: AgentInput,
        output_type: type[T],
        ctx: RunContext,
        override: Override | None = None,
    ) -> AgentResult[T]:
        if ctx.tool_factory:
            specs, execute = ctx.tool_factory(role)
            ctx = replace(ctx, tool_specs=specs, execute_tool=execute)
        route = self._router.resolve(role, override)
        recorded = ctx.record_usage is not None
        accumulator = UsageAccumulator(ctx.record_usage)
        total_usage = accumulator.total
        ctx = replace(ctx, record_usage=accumulator)
        log = AttemptLog()
        started = time.monotonic()
        last: Exception | None = None
        for alias in route.chain:
            try:
                output, _ = await self._call_alias(route, alias, role, inp, output_type, ctx, log)
                result = AgentResult[output_type](  # type: ignore[valid-type]
                    role=role,
                    output=output,
                    alias=alias,
                    model=self._router.model_of(alias),
                    usage=total_usage,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    attempts=log.count,
                    retry_reasons=log.reasons,
                    routing_reason=route.reason if alias == route.alias else f"fallback_from_{route.alias}",
                    usage_recorded=recorded,
                )
                if ctx.on_result:
                    ctx.on_result(result)
                return result
            except RetriesExhausted as e:
                last = e
        assert last is not None
        raise last

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
        system = self._cfg.prompt(role)
        messages: list[dict[str, Any]] = [{"role": "user", "content": render_user_message(inp)}]
        usage = Usage()
        schema = output_type.model_json_schema()
        repairs = 0
        while repairs <= self._cfg.retry.structured_output_repair.max_repairs:
            available_tools = ctx.tool_specs
            completion, charged = await metered_call(
                self._chat, self._cfg, ctx, log,
                role=role, alias=alias, system=system, messages=messages, schema=schema,
                temperature=route.temperature,
            )
            usage = Usage(
                tokens_in=usage.tokens_in + charged.tokens_in,
                tokens_out=usage.tokens_out + charged.tokens_out,
                cost_cents=usage.cost_cents + charged.cost_cents,
            )
            if completion.tool_calls:
                if not available_tools:
                    raise LlmError("unexpected_tool_calls")
                if not ctx.execute_tool:
                    raise LlmError("tools_unavailable")
                messages.append(
                    {
                        "role": "assistant",
                        "content": completion.text or None,
                        "tool_calls": completion.tool_calls,
                        **({"_anthropic_content": completion.provider_content} if completion.provider_content else {}),
                    }
                )
                for tool in completion.tool_calls:
                    ctx.check_budget(0)
                    function = tool["function"]
                    entry: dict[str, Any] = {
                        "id": tool["id"],
                        "name": function["name"],
                        "arguments": function["arguments"],
                        "role": role,
                    }
                    if ctx.record_tool:
                        ctx.record_tool({**entry, "status": "started"})
                    value: Any
                    try:
                        args = json.loads(function["arguments"])
                        if not isinstance(args, dict):
                            raise ValueError("arguments must be an object")
                        value = await ctx.execute_tool(function["name"], args)
                    except BudgetExceeded:
                        raise
                    except Exception as exc:
                        if isinstance(exc, PermissionError) and role != "root":
                            if ctx.record_tool:
                                ctx.record_tool({**entry, "status": "failed", "error": type(exc).__name__})
                            raise
                        value = {"error": getattr(exc, "kind", type(exc).__name__)}
                    result_text = json.dumps(value, ensure_ascii=False)
                    if len(result_text.encode("utf-8")) > 16384:
                        value = {
                            "truncated": True,
                            "preview": result_text.encode("utf-8")[:7000].decode("utf-8", errors="ignore"),
                        }
                        result_text = json.dumps(value, ensure_ascii=False)
                    if ctx.record_tool:
                        ctx.record_tool({**entry, "status": "completed", "result": value})
                    messages.append({"role": "tool", "tool_call_id": tool["id"], "content": result_text})
                continue
            try:
                return output_type.model_validate_json(completion.text), usage
            except ValidationError as e:
                repairs += 1
                log.reasons.append("structured_output_invalid")
                messages += [
                    {
                        "role": "assistant",
                        "content": completion.text,
                        **({"_anthropic_content": completion.provider_content} if completion.provider_content else {}),
                    },
                    {"role": "user", "content": f"Your output failed validation. Fix and resend JSON only:\n{e}"},
                ]
        raise LlmError(f"{role}: structured output invalid after repairs")
