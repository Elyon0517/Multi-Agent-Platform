from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from agentlab.core.budget import estimate_cents
from agentlab.core.config import AppConfig
from agentlab.core.llm.retry import AttemptLog, LlmError, RetriesExhausted, call_with_retry
from agentlab.core.ports import RunContext
from agentlab.core.routing import Override, Route, Router
from agentlab.core.schemas import AgentInput, AgentResult, Usage

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class Completion:
    text: str
    tokens_in: int
    tokens_out: int


ChatFn = Callable[..., Awaitable[Completion]]


def render_user_message(inp: AgentInput) -> str:
    return inp.model_dump_json(exclude_none=True, exclude_defaults=True, indent=1)


class StructuredCaller:
    def __init__(self, cfg: AppConfig, chat: ChatFn) -> None:
        self._cfg = cfg
        self._router = Router(cfg)
        self._chat = chat

    async def call(
        self, role: str, inp: AgentInput, output_type: type[T], ctx: RunContext,
        override: Override | None = None,
    ) -> AgentResult[T]:
        route = self._router.resolve(role, override)
        total_usage = Usage()
        recorded = ctx.record_usage is not None
        original_record = ctx.record_usage

        def record(usage: Usage) -> None:
            total_usage.tokens_in += usage.tokens_in
            total_usage.tokens_out += usage.tokens_out
            total_usage.cost_cents += usage.cost_cents
            if original_record:
                original_record(usage)

        ctx = replace(ctx, record_usage=record)
        log = AttemptLog()
        started = time.monotonic()
        last: Exception | None = None
        for alias in route.chain:
            try:
                output, _ = await self._call_alias(route, alias, role, inp, output_type, ctx, log)
                return AgentResult[output_type](  # type: ignore[valid-type]
                    role=role, output=output, alias=alias, model=self._router.model_of(alias), usage=total_usage,
                    latency_ms=int((time.monotonic() - started) * 1000), attempts=log.count,
                    retry_reasons=log.reasons,
                    routing_reason=route.reason if alias == route.alias else f"fallback_from_{route.alias}",
                    usage_recorded=recorded,
                )
            except RetriesExhausted as e:
                last = e
        assert last is not None
        raise last

    async def _call_alias(
        self, route: Route, alias: str, role: str, inp: AgentInput, output_type: type[T],
        ctx: RunContext, log: AttemptLog,
    ) -> tuple[T, Usage]:
        alias_cfg = self._cfg.models.aliases[alias]
        system = self._cfg.prompt(role)
        messages = [{"role": "user", "content": render_user_message(inp)}]
        usage = Usage()
        schema = output_type.model_json_schema()
        for _ in range(self._cfg.retry.structured_output_repair.max_repairs + 1):
            prompt_chars = (len(system.encode()) + len(json.dumps(schema).encode())
                            + sum(len(m["content"].encode()) for m in messages) + 256)
            estimate = estimate_cents(alias_cfg, prompt_chars)

            def check_attempt(estimate: float = estimate) -> None:
                if ctx.reserve_budget:
                    ctx.reserve_budget(estimate)
                else:
                    ctx.check_budget(estimate)

            async def attempt(estimate: float = estimate,
                              messages: tuple[dict[str, str], ...] = tuple(messages)) -> Completion:
                nonlocal usage
                try:
                    completion = await self._chat(model=alias_cfg.model, system=system, messages=list(messages),
                                                  temperature=route.temperature, schema=schema,
                                                  max_output_tokens=alias_cfg.max_output_tokens,
                                                  output_token_parameter=alias_cfg.output_token_parameter)
                    charged = Usage(tokens_in=completion.tokens_in, tokens_out=completion.tokens_out,
                                    cost_cents=alias_cfg.cost_cents(completion.tokens_in, completion.tokens_out))
                except LlmError as exc:
                    charged = Usage(tokens_in=exc.tokens_in, tokens_out=exc.tokens_out,
                                    cost_cents=alias_cfg.cost_cents(exc.tokens_in, exc.tokens_out))
                    if ctx.record_usage:
                        ctx.record_usage(charged)
                    raise
                finally:
                    if ctx.release_budget:
                        ctx.release_budget(estimate)
                usage = Usage(tokens_in=usage.tokens_in + charged.tokens_in,
                              tokens_out=usage.tokens_out + charged.tokens_out,
                              cost_cents=usage.cost_cents + charged.cost_cents)
                if ctx.record_usage:
                    ctx.record_usage(charged)
                return completion

            completion = await call_with_retry(attempt, self._cfg.retry.llm_call, log, check_attempt)
            try:
                return output_type.model_validate_json(completion.text), usage
            except ValidationError as e:
                log.reasons.append("structured_output_invalid")
                messages += [
                    {"role": "assistant", "content": completion.text},
                    {"role": "user", "content": f"Your output failed validation. Fix and resend JSON only:\n{e}"},
                ]
        raise LlmError(f"{role}: structured output invalid after repairs")
