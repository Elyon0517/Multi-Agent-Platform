from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any, Literal, TypeVar

from pydantic import BaseModel

from agentlab.core.budget import BudgetExceeded, BudgetGuard, estimate_cents
from agentlab.core.config import AppConfig
from agentlab.core.llm.retry import ParallelFailure
from agentlab.core.llm.structured import render_user_message
from agentlab.core.loop.arbiter import arbitrate
from agentlab.core.loop.convergence import gate_fingerprints, is_oscillating, review_fingerprints
from agentlab.core.loop.hooks import NoHooks, RunHooks
from agentlab.core.loop.states import ACTIVE, TERMINAL, check_transition
from agentlab.core.monitor import UsageRecorder, commit_result_usage, recover_run_calls
from agentlab.core.ports import (
    AgentRuntime,
    BlobStore,
    EventBus,
    GateAdapter,
    RunBusy,
    RunContext,
    Store,
    Workspace,
    execution_error_reason,
)
from agentlab.core.project_config import Dispatch, ProjectSettings
from agentlab.core.schemas import (
    AgentInput,
    AgentResult,
    Approval,
    ApprovalStatus,
    ArbiterAction,
    ArbiterDecision,
    Artifact,
    ArtifactKind,
    CoderOutput,
    Event,
    EventType,
    GateMode,
    GateResult,
    Iteration,
    Plan,
    Run,
    RunStatus,
    SignoffReport,
    Step,
    Usage,
    Verdict,
    utcnow,
)

T = TypeVar("T", bound=BaseModel)
S = RunStatus
Decision = Literal["approve", "reject", "abort"]
SUMMARY_CHARS = 280
log = logging.getLogger(__name__)


def summarize(out: BaseModel) -> str:
    if isinstance(out, Verdict):
        text = f"{out.verdict}: {out.summary}" + "".join(f"\n- [{f.severity}] {f.issue}" for f in out.findings)
    elif isinstance(out, CoderOutput):
        text = "edited " + ", ".join(e.path for e in out.edits)
    elif isinstance(out, Plan):
        text = out.summary + "".join(f"\n{i + 1}. {s}" for i, s in enumerate(out.steps))
    else:
        text = out.model_dump_json()
    return text[:SUMMARY_CHARS]


class Driver:
    def __init__(
        self,
        cfg: AppConfig,
        store: Store,
        blobs: BlobStore,
        bus: EventBus,
        runtime: AgentRuntime,
        gate: GateAdapter | None,
        workspace: Workspace,
        hooks: RunHooks | None = None,
    ) -> None:
        self.cfg, self.store, self.blobs, self.bus = cfg, store, blobs, bus
        self.runtime, self.gate, self.workspace = runtime, gate, workspace
        self.runtime_factory: Callable[[], AgentRuntime] | None = None
        self.hooks: RunHooks = hooks or NoHooks()
        self.recovery_options: dict[str, Any] = {}
        self._event_buffer: list[Event] | None = None
        self._finished: set[str] = set()
        self._agent_inputs: dict[tuple[str, str, int, str], dict[str, AgentInput]] = {}
        self._completed_agents: dict[tuple[str, str, int, str], AgentResult[Any]] = {}
        self._handlers: dict[S, Callable[[Run], Awaitable[None]]] = {
            S.PLANNING: self._planning,
            S.CODING: self._coding,
            S.GATING: self._gating,
            S.REVIEWING: self._reviewing,
            S.ARBITRATING: self._arbitrating,
        }

    def create(self, goal: str, **overrides: Any) -> Run:
        with self.store.lock_run("workspace:" + str(self.workspace.root)):
            self._check_workspace_available()
            self.workspace.begin_run()
            return self._create(goal, **overrides)

    async def create_async(self, goal: str, **overrides: Any) -> Run:
        with self.store.lock_run("workspace:" + str(self.workspace.root)):
            self._check_workspace_available()
            await asyncio.to_thread(self.workspace.begin_run)
            return self._create(goal, **overrides)

    def _check_workspace_available(self) -> None:
        if any(
            r.workspace == str(self.workspace.root) and r.status not in {S.DONE, S.CANCELLED}
            for r in self.store.list_runs()
        ):
            raise RunBusy("workspace already has an unfinished run; finish or abort it before starting another")

    def _create(self, goal: str, on_create: Callable[[Run], None] | None = None, **overrides: Any) -> Run:
        defaults = {"max_iter": self.cfg.budget.loop.max_iter, "budget_cents": self.cfg.budget.default_run_budget_cents}
        run = Run(goal=goal, workspace=str(self.workspace.root), **{**defaults, **overrides})
        with self._atomic():
            self.store.create_run(run)
            self._checkpoint(run)
            if on_create:
                on_create(run)
            self._emit(run, EventType.RUN_CREATED, goal=goal, roles=self._roster())
        return run

    async def run(self, run_id: str) -> Run:
        with self.store.lock_run(run_id), self.store.lock_run("workspace:" + str(self.workspace.root)):
            self._reload_checkpoint(run_id)
            run = await self._run(run_id)
        # Bookkeeping after a pause or the end (a summary may call a model for many seconds) runs once the
        # locks are released, so an approval can be decided the moment it appears.
        return await self._after_run(run)

    async def _run(self, run_id: str) -> Run:
        run = self.store.get_run(run_id)
        unknown = [
            a for a in self.store.records("attempt") if a.get("run_id") == run_id and a.get("status") == "in_flight"
        ]
        if unknown:
            recover_run_calls(self.store, run_id)
        if unknown and run.status in ACTIVE:
            self._escalate(run, "interrupted_call", {"attempt_ids": [a["id"] for a in unknown]}, on_approve=run.status)
        while run.status in ACTIVE:
            try:
                await self._handlers[run.status](run)
            except BudgetExceeded as e:
                self._escalate(
                    run, "budget_exceeded", {"required_budget_cents": e.required_budget_cents}, on_approve=run.status
                )
            except Exception as exc:
                run = self.store.get_run(run_id)
                # Exceptions can contain prompts/keys. Persist only a safe error class.
                reason = execution_error_reason(exc)
                self._escalate(
                    run,
                    reason,
                    {"error_type": type(exc).__name__, "error_kind": getattr(exc, "kind", "execution_error")},
                    on_approve=run.status,
                )
                log.error("run %s paused in %s: %s", run.id, run.status, type(exc).__name__)
            self.store.save_run(run)
        return run

    async def _after_run(self, run: Run) -> Run:
        if run.status == RunStatus.WAITING_HUMAN:
            on_waiting = getattr(self.hooks, "on_waiting", None)
            if on_waiting:
                try:
                    await on_waiting(run)
                except Exception:
                    log.exception("on_waiting hook failed for run %s", run.id)
        if run.status in TERMINAL and run.id not in self._finished:
            self._finished.add(run.id)
            self._clear_agent_cache(run.id)
            close = getattr(self.workspace, "close", None)
            if close:
                close()
            release = getattr(self.workspace, "release", None)
            if release:
                try:
                    await asyncio.to_thread(release)
                except Exception:  # a leftover worktree is harmless; never fail the finished run
                    log.exception("worktree cleanup failed for run %s", run.id)
            try:
                await self.hooks.on_finished(run)
            except Exception:  # post-run bookkeeping must not change the outcome
                log.exception("on_finished hook failed for run %s", run.id)
        return run

    async def cancel(self, run_id: str, by: str = "human") -> Run:
        """Stop a run in any non-terminal state (the caller has already cancelled its executing task)."""
        with self.store.lock_run(run_id):
            run = self.store.get_run(run_id)
            if run.status in TERMINAL:
                return run
            # A model call cut off by the stop may have been billed; record it as unmetered, never retried.
            recover_run_calls(self.store, run_id)
            with self._atomic():
                approval = self.store.pending_approval(run_id)
                if approval:
                    approval.status, approval.decided_by, approval.decided_at = ApprovalStatus.ABORTED, by, utcnow()
                    self.store.save_approval(approval)
                for item in self.store.records("attempt"):
                    if item.get("run_id") == run_id and item.get("status") == "in_flight":
                        self.store.put_record("attempt", item["id"], {**item, "status": "unknown_closed"})
                run.paused_reason = None
                self._advance_committed(run, S.CANCELLED)
            self._clear_agent_cache(run_id)
        return await self._after_run(run)

    def decide(
        self,
        run_id: str,
        decision: Decision,
        feedback: str | None = None,
        by: str = "human",
        budget_cents: float | None = None,
        max_iter: int | None = None,
    ) -> Run:
        with self.store.lock_run(run_id), self._atomic():
            self._reload_checkpoint(run_id)
            return self._decide(run_id, decision, feedback, by, budget_cents, max_iter)

    def _decide(
        self,
        run_id: str,
        decision: Decision,
        feedback: str | None = None,
        by: str = "human",
        budget_cents: float | None = None,
        max_iter: int | None = None,
    ) -> Run:
        run = self.store.get_run(run_id)
        approval = self.store.pending_approval(run_id)
        if run.status != S.WAITING_HUMAN or approval is None:
            raise ValueError(f"run {run_id} is not waiting for a human decision")
        if budget_cents is not None and budget_cents <= 0:
            raise ValueError("budget must be positive")
        if max_iter is not None and not 1 <= max_iter <= 50:
            raise ValueError("max_iter must be between 1 and 50")
        if (
            approval.reason == "dispatch_invalid"
            and decision != "abort"
            and (decision != "reject" or not (feedback or "").strip())
        ):
            raise ValueError("reject with feedback to regenerate invalid model/task assignments")
        if decision == "approve":
            if approval.reason in {"reviewer_conflict", "inconsistent_verdict"} and not (feedback or "").strip():
                raise ValueError("feedback is required to resolve reviewer disagreement")
            if approval.reason == "budget_exceeded":
                required = approval.payload.get("required_budget_cents")
                if (
                    budget_cents is None
                    or budget_cents <= run.budget_cents
                    or (required is not None and budget_cents < float(required))
                ):
                    raise ValueError("increase budget to at least the required amount before resuming")
            if approval.reason == "max_iter_exceeded" and (max_iter is None or max_iter <= run.max_iter):
                raise ValueError("increase max_iter before resuming")
            if approval.on_approve == S.DONE and approval.reason != "signoff":
                raise ValueError("only signoff approval can complete a run")
            if approval.reason == "signoff":
                # Isolated runs land in the user's working tree now; a conflict leaves the approval pending.
                integrate = getattr(self.workspace, "integrate_back", None)
                if integrate:
                    integrate()
        if (
            decision != "abort"
            and self.runtime_factory is not None
            and not (decision == "approve" and approval.on_approve == S.DONE)
        ):
            self.runtime = self.runtime_factory()  # reread gateway credentials when resuming
        run.budget_cents = budget_cents if budget_cents is not None else run.budget_cents
        run.max_iter = max_iter if max_iter is not None else run.max_iter
        reject_state = S.CODING if self._latest_text(run, "plan") else S.PLANNING
        status_by_decision = {"approve": approval.on_approve, "reject": reject_state, "abort": S.CANCELLED}
        approval_by_decision = {
            "approve": ApprovalStatus.APPROVED,
            "reject": ApprovalStatus.REJECTED,
            "abort": ApprovalStatus.ABORTED,
        }
        approval.status, approval.decided_by = approval_by_decision[decision], by
        approval.feedback, approval.decided_at = feedback, utcnow()
        self.store.save_approval(approval)
        if decision == "reject" or (
            decision == "approve"
            and approval.reason
            in {"oscillation_detected", "reviewer_conflict", "inconsistent_verdict", "workspace_escape"}
        ):
            if decision == "reject" or feedback:
                self._save_artifact(run, "feedback", feedback or "rejected without feedback", "human")
            run.iteration_base = len(self.store.iterations(run_id))
        if decision in {"reject", "abort"}:
            self._clear_agent_cache(run.id)
        if approval.reason == "interrupted_call":
            recover_run_calls(self.store, run_id)
            for item in self.store.records("attempt"):
                if item.get("run_id") == run_id and item.get("status") == "in_flight":
                    item["status"] = "unknown_authorized_retry" if decision == "approve" else "unknown_closed"
                    self.store.put_record("attempt", item["id"], item)
        run.paused_reason = None
        self._emit(run, EventType.APPROVAL_DECIDED, actor=by, decision=decision, feedback=feedback)
        self._advance(run, status_by_decision[decision])
        self.store.save_run(run)
        return run

    async def _planning(self, run: Run) -> None:
        settings_data = self.recovery_options.get("project_settings")
        if settings_data:
            settings = ProjectSettings.model_validate(settings_data)
            if settings.mode == "auto" and not self.store.records("dispatch_" + run.id):
                context = {
                    "available_models": {
                        a: {**self.cfg.models.aliases[a].model_dump(mode="json"), "tier": self.cfg.models.tiers[a]}
                        for a in settings.allowed_aliases or self.cfg.models.aliases
                    },
                    "default_aliases": {
                        r: p.primary
                        for r, p in self.cfg.model_policy.roles.items()
                        if p.primary in (settings.allowed_aliases or self.cfg.models.aliases)
                    },
                    "roles": sorted(set(self.cfg.model_policy.roles) - {"root", "supervisor", "project-planner"}),
                    "reviewer_max_tiers": {
                        role: max(
                            self.cfg.models.tiers[self.cfg.model_policy.roles[role].primary],
                            self.cfg.model_policy.override.reviewer_min_tier,
                        )
                        for role in self.cfg.reviewer_roles
                    },
                    "instruction": (
                        "Assign each worker a model alias and task. Keep all reviewers independent; "
                        "Use configured gates when available; never skip human approvals. "
                        "When tier-eligible reviewer models contain at least two distinct model IDs, "
                        "assign correctness-reviewer and arch-reviewer different model IDs. "
                        "Different aliases for the same model ID do not count."
                    ),
                }
                result = await self._agent(
                    run,
                    "supervisor",
                    self._input(run, context=context, feedback=self._latest_text(run, "feedback")),
                    Dispatch,
                )
                try:
                    result.output.validate_for(self.cfg, settings)
                except ValueError as exc:
                    with self._atomic():
                        self._save_artifact(run, "dispatch", result.output.model_dump_json(), "supervisor")
                        self._escalate(run, "dispatch_invalid", {"detail": str(exc)}, on_approve=S.PLANNING)
                    return
                with self._atomic():
                    data = self.cfg.model_dump(mode="json")
                    for role, binding in result.output.assignments.items():
                        data["model_policy"]["roles"][role]["primary"] = binding.alias
                        data["model_policy"]["roles"][role]["fallback"] = []
                    self.cfg = AppConfig.model_validate(data)
                    self.recovery_options["assignments"] = result.output.model_dump(mode="json")["assignments"]
                    self.store.put_record("dispatch_" + run.id, run.id, result.output.model_dump(mode="json"))
                    self._save_artifact(run, "dispatch", result.output.model_dump_json(), "supervisor")
                    # Keep dispatch separate from the planner's plan artifact.
                    arts = self.store.artifacts(run.id, "dispatch")
                    self.recovery_options["dispatch_artifact_id"] = arts[-1].id
                    self._checkpoint(run)
                if self.runtime_factory:
                    self.runtime = self.runtime_factory()
        res = await self._agent(run, "planner", self._input(run, feedback=self._latest_text(run, "feedback")), Plan)
        with self._atomic():
            self._save_artifact(run, "plan", res.output.model_dump_json(), "planner", to="coder")
            self._advance(run, S.CODING)

    async def _coding(self, run: Run) -> None:
        if len(self.store.iterations(run.id)) - run.iteration_base >= run.max_iter:
            self._escalate(run, "max_iter_exceeded", {"max_iter": run.max_iter})
            return
        res = await self._agent(run, "coder", self._coder_input(run), CoderOutput)
        self.workspace.apply_edits(res.output.edits)
        diff = await self.workspace.diff()
        if not diff.strip():
            # Nothing changed: reviewing an empty diff only spends budget, so ask the user right away.
            self._escalate(run, "no_changes", {"blocked_reason": (res.output.blocked_reason or "")[:2000]},
                           on_approve=S.CODING)
            return
        with self._atomic():
            self._save_artifact(run, "diff", diff, "coder", to="gate" if self.gate else "reviewers")
            if self.gate is None:
                self.store.add_iteration(Iteration(run_id=run.id, n=len(self.store.iterations(run.id)) + 1,
                                                   phase=S.REVIEWING,
                                                   diff_hash=hashlib.sha256(diff.encode()).hexdigest()))
                self._advance(run, S.REVIEWING)
            else:
                self._advance(run, S.GATING)

    async def _gating(self, run: Run) -> None:
        if self.gate is None:
            raise RuntimeError("GATING requires a configured gate")
        diff = self._latest_text(run, "diff") or ""
        self._emit(run, EventType.STEP_STARTED, actor="gate", role="gate")
        gr = await self.gate.run(self.workspace.root, GateMode.FAST)
        with self._atomic():
            self._save_artifact(run, "gate", gr.model_dump_json(), "gate", to="coder")
            self._emit(run, EventType.GATE_FINISHED, actor="gate", passed=gr.passed, failed_at=gr.failed_at)
            it = Iteration(
                run_id=run.id,
                n=len(self.store.iterations(run.id)) + 1,
                phase=S.GATING,
                diff_hash=hashlib.sha256(diff.encode()).hexdigest()[:16],
                gate_result=gr,
                finding_set=[] if gr.passed else gate_fingerprints(gr),
            )
            self.store.add_iteration(it)
            if is_oscillating(self._round_iterations(run)):
                self._escalate(run, "oscillation_detected", {"iteration": it.n})
            elif not gr.passed:
                self._advance(run, S.CODING)
            else:
                self._advance(run, S.REVIEWING)

    async def _reviewing(self, run: Run) -> None:
        inp = self._input(run, diff=self._latest_text(run, "diff"), gate=self._last_iteration(run).gate_result)
        inp.iteration = self._last_iteration(run).n
        results = await self._agents(run, self.cfg.reviewer_roles, inp, Verdict)
        verdicts = [
            r.output.model_copy(
                update={
                    "reviewer_id": f"{r.role}@{r.model}",
                    "findings": [
                        f.model_copy(update={"reviewer_id": f"{r.role}@{r.model}"}) for f in r.output.findings
                    ],
                }
            )
            for r in results
        ]
        with self._atomic():
            for v in verdicts:
                self._save_artifact(run, "review", v.model_dump_json(), v.reviewer_id.split("@")[0], to="arbiter")
            it = self._last_iteration(run).model_copy(
                update={"phase": S.REVIEWING, "verdicts": verdicts, "finding_set": review_fingerprints(verdicts)}
            )
            self.store.save_iteration(it)
            self._advance(run, S.ARBITRATING)
        try:
            await self.hooks.after_reviews(run, verdicts)
        except Exception:  # memory write-back is best-effort
            log.exception("after_reviews hook failed for run %s", run.id)

    async def _arbitrating(self, run: Run) -> None:
        verdicts = self._last_iteration(run).verdicts
        d = arbitrate(verdicts, self.cfg.budget.loop.blocking_confidence_threshold)
        self._emit(run, EventType.ARBITER_DECISION, actor="arbiter", action=d.action, reason=d.reason)
        if d.action == ArbiterAction.BACK_TO_CODER and is_oscillating(self._round_iterations(run)):
            self._escalate(run, "oscillation_detected", {"finding_set": self._last_iteration(run).finding_set})
        elif d.action == ArbiterAction.BACK_TO_CODER:
            with self._atomic():
                self._save_artifact(run, "arbiter", d.model_dump_json(), "arbiter", to="coder")
                self._advance(run, S.CODING)
        elif d.action == ArbiterAction.ESCALATE:
            self._escalate(run, d.reason, d.model_dump(mode="json"))
        else:
            await self._final_gate(run, d)

    async def _final_gate(self, run: Run, d: ArbiterDecision) -> None:
        if self.gate is not None:
            gr = await self.gate.run(self.workspace.root, GateMode.FULL)
            with self._atomic():
                self._save_artifact(run, "gate", gr.model_dump_json(), "gate", to="human")
                self._emit(run, EventType.GATE_FINISHED, actor="gate", passed=gr.passed, mode="full")
                if not gr.passed:
                    self._advance(run, S.CODING)
                    return
        plan_text = self._latest_text(run, "plan")
        plan = Plan.model_validate_json(plan_text) if plan_text else None
        report = SignoffReport(
            goal=run.goal,
            acceptance_criteria=list(plan.acceptance_criteria) if plan else [],
            automated_checks="passed" if self.gate is not None else "not_run",
            findings=[finding.model_copy(deep=True) for verdict in self._last_iteration(run).verdicts
                      for finding in verdict.findings],
        )
        self._escalate(run, "signoff", {
            "diff_ref": self._latest(run, "diff").content_ref,
            "automated_checks": "passed" if self.gate is not None else "not_run",
        }, on_approve=S.DONE, report=report)

    async def _agent(self, run: Run, role: str, inp: AgentInput, out: type[T]) -> AgentResult[T]:
        return (await self._agents(run, [role], inp, out))[0]

    async def _context(self, run: Run, role: str, inp: AgentInput) -> dict[str, Any]:
        try:
            settings = self.recovery_options.get("project_settings")
            if settings:
                inp = inp.model_copy(update={"context": {**inp.context, "retrieval_settings": settings}})
            return await self.hooks.context_for(run, role, inp)
        except Exception:  # an agent without memory context is better than a dead run
            log.exception("context_for hook failed for %s in run %s", role, run.id)
            return {}

    async def _agents(self, run: Run, roles: list[str], inp: AgentInput, out: type[T]) -> list[AgentResult[T]]:
        guard = BudgetGuard(
            run,
            self.cfg.budget.warn_ratio,
            lambda r: self._emit(r, EventType.BUDGET_WARNING, cost_cents=r.cost_cents, budget_cents=r.budget_cents),
        )

        def record_usage(usage: Any) -> None:
            with self._atomic():
                guard.record(usage)
                self.store.save_run(run)
                self._checkpoint(run)

        ctx = RunContext(
            run=run,
            check_budget=guard.check,
            record_usage=UsageRecorder(self.store, "run", run.id, run.project_id, record_usage),
            reserve_budget=guard.reserve,
            release_budget=guard.release,
        )
        for role in roles:
            self._emit(run, EventType.STEP_STARTED, actor=role, role=role, iteration=inp.iteration)
        batch_hash = hashlib.sha256((inp.model_dump_json(exclude={"context"}) + json.dumps(roles)).encode()).hexdigest()
        # P2 checkpoints used an input-only hash; reuse paid legacy batches when roles match.
        legacy_hash = hashlib.sha256(inp.model_dump_json(exclude={"context"}).encode()).hexdigest()
        legacy_key = (run.id, run.status.value, inp.iteration, legacy_hash)
        if legacy_key in self._agent_inputs and set(self._agent_inputs[legacy_key]) == set(roles):
            batch_hash = legacy_hash
        batch_key = (run.id, run.status.value, inp.iteration, batch_hash)
        if batch_key not in self._agent_inputs:
            files = await self.workspace.context_files()
            self._agent_inputs[batch_key] = {
                r: inp.model_copy(
                    update={
                        "context": {
                            **inp.context,
                            "files": files,
                            **await self._context(run, r, inp),
                            "assignment": self._assignment(r),
                            "conversation": self.recovery_options.get("conversation", []),
                        }
                    }
                )
                for r in roles
            }
        self._checkpoint(run)
        inputs = self._agent_inputs[batch_key]

        def cache_key(role: str) -> tuple[str, str, int, str]:
            return (run.id, run.status.value, inp.iteration, role + batch_hash)

        pending = {r: inputs[r] for r in roles if cache_key(r) not in self._completed_agents}
        estimates = {
            r: estimate_cents(
                self.cfg.models.aliases[self.cfg.model_policy.roles[r].primary],
                len(self.cfg.prompt(r).encode())
                + len(render_user_message(i).encode())
                + len(json.dumps(out.model_json_schema()).encode())
                + 256,
            )
            for r, i in pending.items()
        }

        def completed(r: AgentResult[Any]) -> None:
            if cache_key(r.role) in self._completed_agents:
                return
            settings = self.recovery_options.get("project_settings") or {}
            if settings.get("mode") == "manual":
                r.routing_reason = "project_manual_binding"
            elif self.recovery_options.get("assignments", {}).get(r.role):
                r.routing_reason = "supervisor_dispatch"
            self._completed_agents[cache_key(r.role)] = r
            commit_result_usage(ctx, r)
            attempts = [
                a
                for a in self.store.records("attempt")
                if a.get("batch_key") == list(batch_key) and a.get("role") == r.role
            ]
            if attempts:
                r.prompt_ref = attempts[-1].get("prompt_ref")
                r.response_ref = attempts[-1].get("response_ref")
            else:
                r.prompt_ref = self.blobs.put(inputs[r.role].model_dump_json())[0]
                r.response_ref = self.blobs.put(r.output.model_dump_json())[0]
            self.store.add_step(
                Step(
                    run_id=run.id,
                    iteration_n=inp.iteration,
                    role=r.role,
                    model_alias=r.alias,
                    model=r.model,
                    prompt_ref=r.prompt_ref,
                    response_ref=r.response_ref,
                    usage=r.usage,
                    latency_ms=r.latency_ms,
                    attempt_count=r.attempts,
                    retry_reasons=r.retry_reasons,
                    routing_reason=r.routing_reason,
                )
            )
            self._emit(
                run,
                EventType.STEP_FINISHED,
                actor=r.role,
                role=r.role,
                model=r.model,
                cost_cents=r.usage.cost_cents,
                tokens=r.usage.tokens_in + r.usage.tokens_out,
                tokens_in=r.usage.tokens_in,
                tokens_out=r.usage.tokens_out,
                latency_ms=r.latency_ms,
                iteration=inp.iteration,
                summary=summarize(r.output),
                cumulative_cost_cents=run.cost_cents,
                cumulative_tokens_in=run.tokens_in,
                cumulative_tokens_out=run.tokens_out,
            )
            self.store.save_run(run)
            self._checkpoint(run)

        def committed(r: AgentResult[Any]) -> None:
            with self._atomic():
                completed(r)

        # External (MCP) tools are resolved up front because tool_factory is synchronous.
        external: dict[str, Any] = {}
        external_tools = getattr(self.hooks, "external_tools", None)
        if external_tools:
            for role in roles:
                try:
                    external[role] = await external_tools(role)
                except Exception:  # missing external tools must not stop the run
                    log.exception("external tools unavailable for %s", role)

        def tool_factory(role: str) -> Any:
            from agentlab.core.llm.tools import WorkerTools

            async def search(query: str) -> dict[str, Any]:
                return await self.hooks.context_for(
                    run.model_copy(update={"goal": query}), role, inp.model_copy(update={"goal": query})
                )

            tools = WorkerTools(role, self.cfg.agents[role].tool_grants, self.workspace, self.gate, search)
            extra = external.get(role)
            if not extra:
                return tools.specs, tools.execute
            extra_specs, extra_execute = extra
            names = {spec["function"]["name"] for spec in extra_specs}

            async def execute(name: str, args: dict[str, Any]) -> Any:
                return await (extra_execute if name in names else tools.execute)(name, args)

            return [*tools.specs, *extra_specs], execute

        def record_tool(payload: dict[str, Any]) -> None:
            with self._atomic():
                ref, _ = self.blobs.put(json.dumps(payload, ensure_ascii=False))
                self._emit(
                    run,
                    EventType.STEP_TOOL_CALL,
                    actor=payload.get("role", "agent"),
                    role=payload.get("role"),
                    tool=payload["name"],
                    status=payload["status"],
                    tool_call_id=payload["id"],
                    content_ref=ref,
                )
                self._checkpoint(run)

        ctx = replace(
            ctx,
            tool_factory=tool_factory,
            record_tool=record_tool,
            on_result=committed,
            attempt_started=lambda data: self._attempt_started(run, {**data, "batch_key": list(batch_key)}),
            attempt_finished=self._attempt_finished,
            usage_transaction=self._atomic,
        )
        # A response may have reached disk just before the process died during validation.
        # Recover valid paid responses even if their AgentResult checkpoint was not committed yet.
        for role in list(pending):
            attempts = [
                a
                for a in self.store.records("attempt")
                if a.get("batch_key") == list(batch_key) and a.get("role") == role
            ]
            if attempts and attempts[-1].get("status") == "completed":
                last = attempts[-1]
                try:
                    output = out.model_validate_json(self.blobs.get(last["response_ref"]))
                except ValueError:
                    continue
                usage = Usage()
                for item in attempts:
                    paid = Usage.model_validate(item.get("usage", {}))
                    usage.tokens_in += paid.tokens_in
                    usage.tokens_out += paid.tokens_out
                    usage.cost_cents += paid.cost_cents
                committed(
                    AgentResult[Any](
                        role=role,
                        output=output,
                        alias=last["alias"],
                        model=last["model"],
                        usage=usage,
                        usage_recorded=True,
                        attempts=len(attempts),
                        routing_reason="recovered_response",
                    )
                )
                pending.pop(role)
        if pending:
            guard.check(sum(estimates[r] for r in pending))
        failure: Exception | None = None
        try:
            if not pending:
                results = []
            elif len(pending) == 1:
                role = next(iter(pending))
                results = [await self.runtime.run_agent(role, pending[role], out, ctx)]
            else:
                results = await self.runtime.run_parallel(pending, out, ctx)
        except ParallelFailure as exc:
            results, failure = exc.results, exc.cause
        for r in results:
            committed(r)
        self.store.save_run(run)
        if failure is not None:
            if isinstance(failure, BudgetExceeded):
                remaining = sum(estimates[r] for r in pending if cache_key(r) not in self._completed_agents)
                raise BudgetExceeded(
                    "budget needed for remaining agents",
                    max(run.cost_cents + remaining, failure.required_budget_cents or 0),
                )
            raise failure
        # Deliver paid outputs even if actual usage exceeded the estimate.
        # The next stage checks its entire batch before making any paid calls.
        return [self._completed_agents[cache_key(r)] for r in roles]

    def _assignment(self, role: str) -> Any:
        settings = self.recovery_options.get("project_settings") or {}
        return (self.recovery_options.get("assignments") or settings.get("bindings", {})).get(role)

    def _clear_agent_cache(self, run_id: str) -> None:
        self._completed_agents = {k: v for k, v in self._completed_agents.items() if k[0] != run_id}
        self._agent_inputs = {k: v for k, v in self._agent_inputs.items() if k[0] != run_id}

    def _input(self, run: Run, **extra: Any) -> AgentInput:
        plan = self._latest_text(run, "plan")
        return AgentInput(
            run_id=run.id,
            iteration=len(self.store.iterations(run.id)) + 1,
            goal=run.goal,
            plan=Plan.model_validate_json(plan) if plan else None,
            **extra,
        )

    def _coder_input(self, run: Run) -> AgentInput:
        pending = self._since_last(run, "diff")
        gate = next((a for a in reversed(pending) if a.kind == "gate"), None)
        arb = next((a for a in reversed(pending) if a.kind == "arbiter"), None)
        fb = next((a for a in reversed(pending) if a.kind == "feedback"), None)
        return self._input(
            run,
            gate=GateResult.model_validate_json(self.blobs.get(gate.content_ref)) if gate else None,
            instructions=ArbiterDecision.model_validate_json(self.blobs.get(arb.content_ref)).instructions
            if arb
            else [],
            feedback=self.blobs.get(fb.content_ref) if fb else None,
        )

    def _escalate(
        self, run: Run, reason: str, payload: dict[str, Any], on_approve: S | None = None,
        report: SignoffReport | None = None,
    ) -> None:
        with self._atomic():
            resume = on_approve or (S.CODING if self._latest_text(run, "plan") else S.PLANNING)
            if reason == "oscillation_detected":
                resume = S.CODING
            self.store.create_approval(Approval(
                run_id=run.id, reason=reason, payload=payload, on_approve=resume, report=report,
            ))
            run.paused_reason = reason
            self._emit(run, EventType.APPROVAL_REQUESTED, actor="supervisor", reason=reason, payload=payload,
                       report=report.model_dump(mode="json") if report else None)
            self._advance(run, S.WAITING_HUMAN)

    def _advance(self, run: Run, dst: S) -> None:
        with self._atomic():
            self._advance_committed(run, dst)

    def _advance_committed(self, run: Run, dst: S) -> None:
        check_transition(run.status, dst)
        src, run.status = run.status, dst
        if dst != S.WAITING_HUMAN and src != S.WAITING_HUMAN:
            self._clear_agent_cache(run.id)
        self.store.save_run(run)
        self._checkpoint(run)
        self._emit(run, EventType.RUN_STATUS, src=src, dst=dst, terminal=dst in TERMINAL)

    def _save_artifact(self, run: Run, kind: ArtifactKind, content: str, by: str, to: str | None = None) -> None:
        ref, sha = self.blobs.put(content)
        art = Artifact(run_id=run.id, kind=kind, sha256=sha, content_ref=ref)
        self.store.add_artifact(art)
        self._emit(run, EventType.ARTIFACT_CREATED, actor=by, kind=kind, artifact_id=art.id, to=to)

    def _emit(self, run: Run, type_: EventType, actor: str = "driver", **payload: Any) -> None:
        event = self.store.append_event(Event(run_id=run.id, type=type_, actor=actor, payload=payload))
        if self._event_buffer is not None:
            self._event_buffer.append(event)
        else:
            self.bus.publish(event)

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        if self._event_buffer is not None:
            with self.store.transaction():
                yield
            return
        events: list[Event] = []
        inputs, results = self._agent_inputs.copy(), self._completed_agents.copy()
        self._event_buffer = events
        try:
            with self.store.transaction():
                yield
        except BaseException:
            self._agent_inputs, self._completed_agents = inputs, results
            raise
        else:
            for event in events:
                self.bus.publish(event)
        finally:
            self._event_buffer = None

    def _checkpoint(self, run: Run) -> None:
        export = getattr(self.workspace, "export_state", None)
        cfg = self.cfg.model_dump(mode="json")
        cfg["frozen_prompts"] = {role: self.cfg.prompt(role) for role in self.cfg.agents}
        self.store.save_checkpoint(
            run.id,
            {
                "version": 1,
                "config": cfg,
                "options": self.recovery_options,
                "workspace": export() if export else None,
                "inputs": [
                    {"key": list(k), "roles": {r: i.model_dump(mode="json") for r, i in v.items()}}
                    for k, v in self._agent_inputs.items()
                    if k[0] == run.id
                ],
                "results": [
                    {"key": list(k), "result": v.model_dump(mode="json")}
                    for k, v in self._completed_agents.items()
                    if k[0] == run.id
                ],
            },
        )

    def _reload_checkpoint(self, run_id: str) -> None:
        data = self.store.checkpoint(run_id)
        if data is None:
            return
        new_cfg = AppConfig.model_validate(data["config"])
        changed = new_cfg.model_dump() != self.cfg.model_dump()
        self.cfg = new_cfg
        if changed and self.runtime_factory and self.store.get_run(run_id).status in ACTIVE:
            self.runtime = self.runtime_factory()
        self._clear_agent_cache(run_id)
        self.restore_checkpoint(data)
        restore = getattr(self.workspace, "restore_state", None)
        if restore and data.get("workspace") and self.store.get_run(run_id).status not in TERMINAL:
            restore(data["workspace"])

    def restore_checkpoint(self, data: dict[str, Any]) -> None:
        if data.get("version") != 1:
            raise ValueError("unsupported checkpoint version")
        self.recovery_options = data["options"]
        for item in data["inputs"]:
            key = item["key"]
            self._agent_inputs[(key[0], key[1], key[2], key[3])] = {
                r: AgentInput.model_validate(i) for r, i in item["roles"].items()
            }
        for item in data["results"]:
            key, value = item["key"], item["result"]
            model = (
                Dispatch
                if value["role"] == "supervisor"
                else Plan
                if value["role"] == "planner"
                else CoderOutput
                if value["role"] == "coder"
                else Verdict
            )
            self._completed_agents[(key[0], key[1], key[2], key[3])] = AgentResult[model].model_validate(value)  # type: ignore[valid-type]

    def _attempt_started(self, run: Run, data: dict[str, Any]) -> str:
        from agentlab.core.schemas import new_id

        attempt_id = new_id()
        prompt = data.pop("prompt")
        ref, _ = self.blobs.put(json.dumps(prompt, ensure_ascii=False))
        self.store.put_record(
            "attempt",
            attempt_id,
            {
                **data,
                "id": attempt_id,
                "run_id": run.id,
                "status": "in_flight",
                "prompt_ref": ref,
                "created_at": utcnow().isoformat(),
            },
        )
        return attempt_id

    def _attempt_finished(self, attempt_id: str, data: dict[str, Any]) -> None:
        item = next(a for a in self.store.records("attempt") if a["id"] == attempt_id)
        response = data.pop("response", None)
        if response is not None:
            item["response_ref"] = self.blobs.put(response)[0]
        item.update(data, finished_at=utcnow().isoformat())
        self.store.put_record("attempt", attempt_id, item)

    def _latest(self, run: Run, kind: ArtifactKind) -> Artifact:
        return self.store.artifacts(run.id, kind)[-1]

    def _latest_text(self, run: Run, kind: ArtifactKind) -> str | None:
        arts = self.store.artifacts(run.id, kind)
        return self.blobs.get(arts[-1].content_ref) if arts else None

    def _since_last(self, run: Run, kind: ArtifactKind) -> list[Artifact]:
        arts = self.store.artifacts(run.id)
        last = max((i for i, a in enumerate(arts) if a.kind == kind), default=-1)
        return arts[last + 1 :]

    def _last_iteration(self, run: Run) -> Iteration:
        return self.store.iterations(run.id)[-1]

    def _round_iterations(self, run: Run) -> list[Iteration]:
        return self.store.iterations(run.id)[run.iteration_base :]

    def _roster(self) -> list[dict[str, str]]:
        return [{"role": r, "kind": a.kind} for r, a in self.cfg.agents.items()]
