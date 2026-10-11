from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from agentlab.core.budget import BudgetExceeded, estimate_cents
from agentlab.core.config import AppConfig
from agentlab.core.llm.retry import AttemptLog, LlmError, RetriesExhausted, call_with_retry
from agentlab.core.monitor import UsageAccumulator, commit_usage
from agentlab.core.ports import RunContext
from agentlab.core.routing import Override, Route, Router
from agentlab.core.schemas import AgentInput, AgentResult, Usage

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class Completion:
    text: str
    tokens_in: int
    tokens_out: int
    tool_calls: list[dict[str, Any]] | None = None
    provider_content: list[dict[str, Any]] | None = None
    usage_present: bool = True


ChatFn = Callable[..., Awaitable[Completion]]


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
        alias_cfg = self._cfg.models.aliases[alias]
        system = self._cfg.prompt(role)
        messages: list[dict[str, Any]] = [{"role": "user", "content": render_user_message(inp)}]
        usage = Usage()
        schema = output_type.model_json_schema()
        repairs = 0
        while repairs <= self._cfg.retry.structured_output_repair.max_repairs:
            # No call-count cap: the budget guard (checked before every attempt and tool) bounds the loop.
            available_tools = ctx.tool_specs
            prompt_chars = (
                len(system.encode())
                + len(json.dumps(schema).encode())
                + len(json.dumps(available_tools or []).encode())
                + len(json.dumps(messages, ensure_ascii=False).encode())
                + 256
            )
            estimate = estimate_cents(alias_cfg, prompt_chars)

            def check_attempt(estimate: float = estimate) -> None:
                if ctx.reserve_budget:
                    ctx.reserve_budget(estimate)
                else:
                    ctx.check_budget(estimate)

            async def attempt(
                estimate: float = estimate,
                messages: tuple[dict[str, Any], ...] = tuple(messages),
                available_tools: list[dict[str, Any]] | None = available_tools,
            ) -> Completion:
                nonlocal usage
                attempt_id = (
                    ctx.attempt_started(
                        {
                            "role": role,
                            "alias": alias,
                            "model": alias_cfg.model,
                            "prompt": {
                                "system": system,
                                "messages": list(messages),
                                "schema": schema,
                                "tools": available_tools or [],
                                "temperature": route.temperature,
                                "max_output_tokens": alias_cfg.max_output_tokens,
                                "output_token_parameter": alias_cfg.output_token_parameter,
                            },
                        }
                    )
                    if ctx.attempt_started
                    else None
                )
                try:
                    completion = await self._chat(
                        model=alias_cfg.model,
                        system=system,
                        messages=list(messages),
                        temperature=route.temperature,
                        schema=schema,
                        max_output_tokens=alias_cfg.max_output_tokens,
                        output_token_parameter=alias_cfg.output_token_parameter,
                        **({"provider": alias_cfg.provider} if alias_cfg.provider != "openai" else {}),
                        **({"tools": available_tools} if available_tools else {}),
                        **({"on_delta": ctx.on_delta} if ctx.on_delta else {}),
                    )
                    charged = Usage(
                        tokens_in=completion.tokens_in,
                        tokens_out=completion.tokens_out,
                        cost_cents=alias_cfg.cost_cents(completion.tokens_in, completion.tokens_out),
                    )
                except LlmError as exc:
                    charged = Usage(
                        tokens_in=exc.tokens_in,
                        tokens_out=exc.tokens_out,
                        cost_cents=alias_cfg.cost_cents(exc.tokens_in, exc.tokens_out),
                    )
                    paid = charged.for_call(
                        role,
                        alias,
                        alias_cfg.model,
                        attempt_id,
                        exc.usage_present or bool(exc.tokens_in or exc.tokens_out),
                    )

                    error_kind = exc.kind

                    def failed() -> None:
                        if attempt_id and ctx.attempt_finished:
                            ctx.attempt_finished(
                                attempt_id,
                                {
                                    "status": "failed",
                                    "error_kind": error_kind,
                                    "usage": charged.model_dump(mode="json"),
                                },
                            )

                    commit_usage(ctx, paid, failed)
                    raise
                except BaseException:
                    commit_usage(ctx, Usage().for_call(role, alias, alias_cfg.model, attempt_id, False))
                    raise
                finally:
                    if ctx.release_budget:
                        ctx.release_budget(estimate)
                usage = Usage(
                    tokens_in=usage.tokens_in + charged.tokens_in,
                    tokens_out=usage.tokens_out + charged.tokens_out,
                    cost_cents=usage.cost_cents + charged.cost_cents,
                )

                def completed() -> None:
                    if attempt_id and ctx.attempt_finished:
                        ctx.attempt_finished(
                            attempt_id,
                            {
                                "status": "completed",
                                "response": completion.text,
                                "tool_calls": completion.tool_calls,
                                "usage": charged.model_dump(mode="json"),
                            },
                        )

                commit_usage(
                    ctx, charged.for_call(role, alias, alias_cfg.model, attempt_id, completion.usage_present), completed
                )
                return completion

            completion = await call_with_retry(attempt, self._cfg.retry.llm_call, log, check_attempt)
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
