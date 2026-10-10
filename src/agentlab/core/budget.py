from __future__ import annotations

from collections.abc import Callable

from agentlab.core.config import AliasCfg
from agentlab.core.schemas import Run, Usage

CHARS_PER_TOKEN = 4


class BudgetExceeded(RuntimeError):
    pass


def estimate_cents(alias: AliasCfg, prompt_chars: int, max_out_tokens: int = 4096) -> float:
    return alias.cost_cents(prompt_chars // CHARS_PER_TOKEN, max_out_tokens)


class BudgetGuard:
    def __init__(self, run: Run, warn_ratio: float, on_warn: Callable[[Run], None]) -> None:
        self._run = run
        self._warn_ratio = warn_ratio
        self._on_warn = on_warn
        self._warned = run.cost_cents >= run.budget_cents * warn_ratio

    def check(self, estimate_cents: float = 0.0) -> None:
        if self._run.cost_cents + estimate_cents > self._run.budget_cents:
            raise BudgetExceeded(
                f"run {self._run.id}: {self._run.cost_cents:.2f}+{estimate_cents:.2f} "
                f"> {self._run.budget_cents:.2f} cents"
            )

    def record(self, usage: Usage) -> None:
        self._run.cost_cents += usage.cost_cents
        self._run.tokens_in += usage.tokens_in
        self._run.tokens_out += usage.tokens_out
        if not self._warned and self._run.cost_cents >= self._run.budget_cents * self._warn_ratio:
            self._warned = True
            self._on_warn(self._run)
