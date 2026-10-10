from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

from agentlab.core.budget import BudgetExceeded
from agentlab.core.config import LlmCallCfg

R = TypeVar("R")


class LlmError(Exception):
    kind: str = "llm_error"


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
        except TimeoutError:
            log.reasons.append("read_timeout")
        except Retryable as e:
            log.reasons.append(e.kind)
        except (NonRetryable, BudgetExceeded):
            raise
        if attempt < cfg.num_retries:
            await sleep(full_jitter(cfg.backoff_base_s, attempt))
    raise RetriesExhausted(log.count, list(log.reasons))
