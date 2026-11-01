"""Per-call primitives shared by every runtime that talks to the gateway.

`metered_call` is one model call with budget reservation, retries, attempt records and usage accounting;
`invoke_tool` is one recorded tool call. Sharing them keeps retry, billing and tool semantics identical.
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from agentlab.core.budget import BudgetExceeded, estimate_cents
from agentlab.core.config import AppConfig
from agentlab.core.llm.retry import AttemptLog, LlmError, call_with_retry
from agentlab.core.monitor import commit_usage
from agentlab.core.ports import RunContext
from agentlab.core.schemas import Usage


@dataclass(frozen=True)
class Completion:
    text: str
    tokens_in: int
    tokens_out: int
    tool_calls: list[dict[str, Any]] | None = None
    provider_content: list[dict[str, Any]] | None = None
    usage_present: bool = True


ChatFn = Callable[..., Awaitable[Completion]]


async def metered_call(
    chat: ChatFn,
    cfg: AppConfig,
    ctx: RunContext,
    log: AttemptLog,
    *,
    role: str,
    alias: str,
    system: str,
    messages: list[dict[str, Any]],
    schema: dict[str, Any],
    temperature: float,
) -> tuple[Completion, Usage]:
    """Call `alias` once with retries; returns the completion and the usage charged across its attempts."""
    alias_cfg = cfg.models.aliases[alias]
    available_tools = ctx.tool_specs
    usage = Usage()
    prompt_chars = (
        len(system.encode())
        + len(json.dumps(schema).encode())
        + len(json.dumps(available_tools or []).encode())
        + len(json.dumps(messages, ensure_ascii=False).encode())
        + 256
    )
    estimate = estimate_cents(alias_cfg, prompt_chars)

    def check_attempt() -> None:
        if ctx.reserve_budget:
            ctx.reserve_budget(estimate)
        else:
            ctx.check_budget(estimate)

    current_attempt: dict[str, str | None] = {"id": None}

    def timed_out() -> None:
        attempt_id = current_attempt["id"]
        if attempt_id and ctx.attempt_finished:
            ctx.attempt_finished(attempt_id, {"status": "failed", "error_kind": "read_timeout"})

    async def attempt(messages: tuple[dict[str, Any], ...] = tuple(messages)) -> Completion:
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
                        "temperature": temperature,
                        "max_output_tokens": alias_cfg.max_output_tokens,
                        "output_token_parameter": alias_cfg.output_token_parameter,
                    },
                }
            )
            if ctx.attempt_started
            else None
        )
        current_attempt["id"] = attempt_id
        try:
            completion = await chat(
                model=alias_cfg.model,
                system=system,
                messages=list(messages),
                temperature=temperature,
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

        paid = charged.for_call(role, alias, alias_cfg.model, attempt_id, completion.usage_present)
        commit_usage(ctx, paid, completed)
        return completion

    completion = await call_with_retry(attempt, cfg.retry.llm_call, log, check_attempt, on_timeout=timed_out)
    return completion, usage


TOOL_RESULT_LIMIT = 16384


async def invoke_tool(ctx: RunContext, role: str, call_id: str, name: str, arguments: str) -> Any:
    """Run one model-requested tool; returns the JSON-safe value to send back to the model."""
    assert ctx.execute_tool is not None
    ctx.check_budget(0)
    entry: dict[str, Any] = {"id": call_id, "name": name, "arguments": arguments, "role": role}
    if ctx.record_tool:
        ctx.record_tool({**entry, "status": "started"})
    value: Any
    try:
        args = json.loads(arguments)
        if not isinstance(args, dict):
            raise ValueError("arguments must be an object")
        value = await ctx.execute_tool(name, args)
    except BudgetExceeded:
        raise
    except Exception as exc:
        if isinstance(exc, PermissionError) and role != "root":
            if ctx.record_tool:
                ctx.record_tool({**entry, "status": "failed", "error": type(exc).__name__})
            raise
        value = {"error": getattr(exc, "kind", type(exc).__name__)}
    result_text = json.dumps(value, ensure_ascii=False)
    if len(result_text.encode("utf-8")) > TOOL_RESULT_LIMIT:
        value = {"truncated": True, "preview": result_text.encode("utf-8")[:7000].decode("utf-8", errors="ignore")}
    if ctx.record_tool:
        ctx.record_tool({**entry, "status": "completed", "result": value})
    return value
