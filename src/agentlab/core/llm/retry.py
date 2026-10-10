from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from agentlab.core.budget import BudgetExceeded
from agentlab.core.config import LlmCallCfg

R = TypeVar("R")


class ParallelFailure(Exception):
    def __init__(self, cause: Exception, results: list[Any]) -> None:
        super().__init__(type(cause).__name__)
        self.cause, self.results = cause, results


class LlmError(Exception):
    kind: str = "llm_error"
    tokens_in: int = 0
    tokens_out: int = 0


class Retryable(LlmError):
    def __init__(self, kind: str, message: str = "") -> None:
        super().__init__(message or kind)
        self.kind = kind


class NonRetryable(LlmError):
    def __init__(self, kind: str, message: str = "") -> None:
        super().__init__(message or kind)
        self.kind = kind


class RetriesExhausted(LlmError):
    def __init__(self, attempts: int, reasons: list[str]) -> None:
        super().__init__(f"exhausted after {attempts} attempts: {reasons}")
        self.attempts = attempts
        self.reasons = reasons


@dataclass
class AttemptLog:
    count: int = 0
    reasons: list[str] = field(default_factory=list)


def full_jitter(base: float, attempt: int) -> float:
    return random.uniform(0, base * (2**attempt))


async def call_with_retry(
    fn: Callable[[], Awaitable[R]],
    cfg: LlmCallCfg,
    log: AttemptLog,
    check_budget: Callable[[], None],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> R:
    for attempt in range(cfg.num_retries + 1):
        check_budget()
        log.count += 1
        try:
            return await asyncio.wait_for(fn(), cfg.timeout_s)
        except TimeoutError as exc:
            if "read_timeout" in cfg.do_not_retry_on or "read_timeout" not in cfg.retry_on:
                raise NonRetryable("read_timeout") from exc
            log.reasons.append("read_timeout")
        except Retryable as e:
            if e.kind in cfg.do_not_retry_on or e.kind not in cfg.retry_on:
                raise NonRetryable(e.kind) from e
            log.reasons.append(e.kind)
        except (NonRetryable, BudgetExceeded):
            raise
        if attempt < cfg.num_retries:
            await sleep(full_jitter(cfg.backoff_base_s, attempt))
    raise RetriesExhausted(log.count, list(log.reasons))
