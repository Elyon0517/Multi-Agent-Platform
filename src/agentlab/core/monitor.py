"""Shared, append-only accounting for model calls across all projects."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from agentlab.core.ports import RunContext, Store
from agentlab.core.schemas import Strict, Usage, utcnow


class UsageSummary(Strict):
    role: str
    calls: int = 0
    unmetered_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    total_tokens: int = 0
    cost_cents: float = 0
    models: list[str] = Field(default_factory=list)


class MonitorUsage(BaseModel):
    agents: list[UsageSummary]
    reviewers: UsageSummary
    total: UsageSummary


class UsageRecorder:
    """One entry point for budget accounting and idempotent model-call ledger writes."""

    def __init__(
        self,
        store: Store,
        source: str,
        ref_id: str,
        project_id: str | None,
        on_usage: Callable[[Usage], None] | None = None,
    ) -> None:
        self.store, self.source, self.ref_id, self.project_id = store, source, ref_id, project_id
        self.on_usage = on_usage

    def preserve(self, usage: Usage) -> bool:
        if usage._call is None:
            return False
        return self.store.append_usage(
            {
                "ts": utcnow().isoformat(),
                "source": self.source,
                "ref_id": self.ref_id,
                "project_id": self.project_id,
                "calls": 1,
                **usage.model_dump(),
                **usage._call,
            }
        )

    def __call__(self, usage: Usage) -> None:
        inserted = usage._call is None or self.preserve(usage)
        if inserted and self.on_usage:
            self.on_usage(usage)


class UsageAccumulator:
    def __init__(self, callback: Callable[[Usage], None] | None) -> None:
        self.callback = callback
        self.total = Usage()

    def __call__(self, usage: Usage) -> None:
        if self.callback:
            self.callback(usage)
        self.total.tokens_in += usage.tokens_in
        self.total.tokens_out += usage.tokens_out
        self.total.cost_cents += usage.cost_cents

    def preserve(self, usage: Usage) -> None:
        preserve = getattr(self.callback, "preserve", None)
        if preserve:
            preserve(usage)


def commit_usage(ctx: RunContext, usage: Usage, finish: Callable[[], None] | None = None) -> None:
    """Keep returned provider usage even when secondary persistence fails."""
    try:
        with ctx.usage_transaction():
            if ctx.record_usage:
                ctx.record_usage(usage)
            if finish:
                finish()
    except BaseException:
        preserve = getattr(ctx.record_usage, "preserve", None)
        if preserve:
            preserve(usage)
        raise


def commit_result_usage(ctx: RunContext, result: Any) -> None:
    if result.usage_recorded:
        return
    usage = result.usage
    if usage._call is None:
        usage = usage.for_call(result.role, result.alias, result.model)
    commit_usage(ctx, usage)
    result.usage_recorded = ctx.record_usage is not None


def summarize(store: Store, agents: dict[str, Any]) -> MonitorUsage:
    rows = {role: UsageSummary(role=role) for role in agents if role != "arbiter"}
    total = UsageSummary(role="total")
    reviewers = UsageSummary(role="reviewer")
    for entry in store.usage_by_role():
        role = entry["role"]
        if role == "arbiter":
            continue
        row = UsageSummary.model_validate(
            {k: (v if v is not None else ([] if k == "models" else 0)) for k, v in entry.items()}
        )
        rows[role] = row
        targets = [total]
        if role in agents and agents[role].kind == "reviewer":
            targets.append(reviewers)
        for target in targets:
            for key in ("calls", "unmetered_calls", "tokens_in", "tokens_out", "total_tokens", "cost_cents"):
                setattr(target, key, getattr(target, key) + getattr(row, key))
            target.models = sorted(set(target.models) | set(row.models))
    return MonitorUsage(
        agents=sorted(rows.values(), key=lambda r: (-r.total_tokens, r.role)),
        reviewers=reviewers,
        total=total,
    )


def recover_run_calls(store: Store, run_id: str) -> None:
    run = store.get_run(run_id)
    for attempt in store.records("attempt"):
        if attempt.get("run_id") == run_id and attempt.get("status") in {
            "in_flight",
            "unknown_authorized_retry",
            "unknown_closed",
        }:
            recover_call(store, "run", run_id, run.project_id, attempt)


def recover_call(store: Store, source: str, ref_id: str, project_id: str | None, attempt: dict[str, Any]) -> None:
    if store.usage_recorded(attempt["id"], source, ref_id):
        return
    usage = Usage.model_validate(attempt.get("usage") or {})
    UsageRecorder(store, source, ref_id, project_id).preserve(
        usage.for_call(
            attempt.get("role", {"turn": "root", "planning": "project-planner",
                                 "summarization": "summarizer"}.get(source, "unknown")),
            attempt.get("alias", "unknown"),
            attempt.get("model", "unknown"),
            attempt["id"],
            "usage" in attempt,
        )
    )


def recover_interrupted_calls(store: Store) -> None:
    """Only classify requests whose owner is no longer holding its execution lock."""
    from agentlab.core.ports import RunBusy

    run_ids = {a["run_id"] for a in store.records("attempt") if a.get("run_id") and a.get("status") == "in_flight"}
    for run_id in run_ids:
        try:
            with store.lock_run(run_id), store.transaction():
                recover_run_calls(store, run_id)
        except RunBusy:
            continue
    for turn in store.records("root_turn"):
        if turn.get("status") != "running":
            continue
        try:
            with store.lock_run("turn:" + turn["thread_id"]), store.transaction():
                for attempt in turn.get("attempts", []):
                    if attempt.get("status") == "in_flight" or "response_ref" not in attempt:
                        recover_call(store, "turn", turn["id"], turn.get("project_id"), attempt)
        except RunBusy:
            continue
    try:
        with store.lock_run("project-creation"), store.transaction():
            plans = {p["id"]: p for p in store.records("planning")}
            for attempt in store.records("planning_call"):
                if attempt.get("status") == "in_flight" and attempt.get("planning_id") in plans:
                    plan = plans[attempt["planning_id"]]
                    recover_call(store, "planning", plan["id"], plan.get("project_id"), attempt)
    except RunBusy:
        pass

    for attempt in store.records("summarizer_call"):
        if attempt.get("status") != "in_flight":
            continue
        try:
            with store.lock_run("summarizer:" + attempt["run_id"]), store.transaction():
                recover_call(store, "summarization", attempt["run_id"], attempt.get("project_id"), attempt)
        except RunBusy:
            continue
