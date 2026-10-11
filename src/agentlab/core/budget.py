from __future__ import annotations

from collections.abc import Callable
from math import ceil

from agentlab.core.config import AliasCfg
from agentlab.core.schemas import Run, Usage


class BudgetExceeded(RuntimeError):
    def __init__(self, message: str, required_budget_cents: float | None = None) -> None:
        super().__init__(message)
        self.required_budget_cents = required_budget_cents


def estimate_cents(alias: AliasCfg, prompt_bytes: int, max_out_tokens: int | None = None) -> float:
    output_cap = max_out_tokens if max_out_tokens is not None else alias.max_output_tokens
    return alias.cost_cents(ceil(prompt_bytes * alias.estimate_input_tokens_per_byte),
                            ceil(output_cap * alias.estimate_output_token_ratio))


class BudgetGuard:
    """Compatibility adapter for usage accounting; monetary limits are disabled globally."""

    def __init__(self, run: Run, warn_ratio: float, on_warn: Callable[[Run], None]) -> None:
        self._run = run
        # Legacy arguments remain accepted; spending is tracked without limits.
        self._run.budget_unlimited = True
        self._reserved = 0.0

    def check(self, estimate_cents: float = 0.0) -> None:
        pass

    def reserve(self, estimate: float) -> None:
        self.check(estimate)
        self._reserved += estimate

    def release(self, estimate: float) -> None:
        self._reserved = max(0.0, self._reserved - estimate)

    def record(self, usage: Usage) -> None:
        self._run.cost_cents += usage.cost_cents
        self._run.tokens_in += usage.tokens_in
        self._run.tokens_out += usage.tokens_out
