from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypeVar

from pydantic import BaseModel

from agentlab.core.budget import BudgetExceeded, BudgetGuard
from agentlab.core.config import AppConfig
from agentlab.core.loop.arbiter import arbitrate
from agentlab.core.loop.convergence import gate_fingerprints, is_oscillating, review_fingerprints
from agentlab.core.loop.hooks import NoHooks, RunHooks
from agentlab.core.loop.states import ACTIVE, TERMINAL, check_transition
from agentlab.core.ports import AgentRuntime, BlobStore, EventBus, GateAdapter, RunContext, Store, Workspace
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
    Step,
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
        self, cfg: AppConfig, store: Store, blobs: BlobStore, bus: EventBus,
        runtime: AgentRuntime, gate: GateAdapter, workspace: Workspace, hooks: RunHooks | None = None,
    ) -> None:
        self.cfg, self.store, self.blobs, self.bus = cfg, store, blobs, bus
        self.runtime, self.gate, self.workspace = runtime, gate, workspace
        self.hooks: RunHooks = hooks or NoHooks()
        self._finished: set[str] = set()
        self._handlers: dict[S, Callable[[Run], Awaitable[None]]] = {
            S.PLANNING: self._planning, S.CODING: self._coding, S.GATING: self._gating,
            S.REVIEWING: self._reviewing, S.ARBITRATING: self._arbitrating,
        }

    def create(self, goal: str, **overrides: Any) -> Run:
        defaults = {"max_iter": self.cfg.budget.loop.max_iter,
                    "budget_cents": self.cfg.budget.default_run_budget_cents}
        run = Run(goal=goal, workspace=str(self.workspace.root), **{**defaults, **overrides})
        self.store.create_run(run)
        self._emit(run, EventType.RUN_CREATED, goal=goal, roles=self._roster())
        return run

    async def run(self, run_id: str) -> Run:
        run = self.store.get_run(run_id)
        while run.status in ACTIVE:
            try:
                await self._handlers[run.status](run)
            except BudgetExceeded as e:
                self._escalate(run, "budget_exceeded", {"detail": str(e)}, on_approve=run.status)
            self.store.save_run(run)
        if run.status in TERMINAL and run.id not in self._finished:
            self._finished.add(run.id)
            try:
                await self.hooks.on_finished(run)
            except Exception:  # post-run bookkeeping must not change the outcome
                log.exception("on_finished hook failed for run %s", run.id)
        return run

    def decide(
        self, run_id: str, decision: Decision, feedback: str | None = None, by: str = "human",
        budget_cents: float | None = None, max_iter: int | None = None,
    ) -> Run:
        run = self.store.get_run(run_id)
        approval = self.store.pending_approval(run_id)
        if run.status != S.WAITING_HUMAN or approval is None:
            raise ValueError(f"run {run_id} is not waiting for a human decision")
        run.budget_cents = budget_cents if budget_cents is not None else run.budget_cents
        run.max_iter = max_iter if max_iter is not None else run.max_iter
        status_by_decision = {"approve": approval.on_approve, "reject": S.CODING, "abort": S.CANCELLED}
        approval_by_decision = {
            "approve": ApprovalStatus.APPROVED, "reject": ApprovalStatus.REJECTED, "abort": ApprovalStatus.ABORTED,
        }
        approval.status, approval.decided_by = approval_by_decision[decision], by
        approval.feedback, approval.decided_at = feedback, utcnow()
        self.store.save_approval(approval)
        if decision == "reject":
            self._save_artifact(run, "feedback", feedback or "rejected without feedback", "human")
            run.iteration_base = len(self.store.iterations(run_id))
        run.paused_reason = None
        self._emit(run, EventType.APPROVAL_DECIDED, actor=by, decision=decision, feedback=feedback)
        self._advance(run, status_by_decision[decision])
        self.store.save_run(run)
        return run

    async def _planning(self, run: Run) -> None:
        res = await self._agent(run, "planner", self._input(run), Plan)
        self._save_artifact(run, "plan", res.output.model_dump_json(), "planner", to="coder")
        self._advance(run, S.CODING)

    async def _coding(self, run: Run) -> None:
        if len(self.store.iterations(run.id)) - run.iteration_base >= run.max_iter:
            self._escalate(run, "max_iter_exceeded", {"max_iter": run.max_iter})
            return
        res = await self._agent(run, "coder", self._coder_input(run), CoderOutput)
        self.workspace.apply_edits(res.output.edits)
        diff = await self.workspace.diff()
        self._save_artifact(run, "diff", diff, "coder", to="gate")
        self._advance(run, S.GATING)

    async def _gating(self, run: Run) -> None:
        diff = self._latest_text(run, "diff") or ""
        self._emit(run, EventType.STEP_STARTED, actor="gate", role="gate")
        gr = await self.gate.run(self.workspace.root, GateMode.FAST)
        self._emit(run, EventType.GATE_FINISHED, actor="gate", passed=gr.passed, failed_at=gr.failed_at)
        it = Iteration(
            run_id=run.id, n=len(self.store.iterations(run.id)) + 1, phase=S.GATING,
            diff_hash=hashlib.sha256(diff.encode()).hexdigest()[:16], gate_result=gr,
            finding_set=[] if gr.passed else gate_fingerprints(gr),
        )
        self.store.add_iteration(it)
        if is_oscillating(self._round_iterations(run)):
            self._escalate(run, "oscillation_detected", {"iteration": it.n})
        elif not gr.passed:
            self._save_artifact(run, "gate", gr.model_dump_json(), "gate", to="coder")
            self._advance(run, S.CODING)
        else:
            self._advance(run, S.REVIEWING)

    async def _reviewing(self, run: Run) -> None:
        inp = self._input(run, diff=self._latest_text(run, "diff"), gate=self._last_iteration(run).gate_result)
        results = await self._agents(run, self.cfg.reviewer_roles, inp, Verdict)
        verdicts = [r.output.model_copy(update={"reviewer_id": f"{r.role}@{r.model}"}) for r in results]
        for v in verdicts:
            self._save_artifact(run, "review", v.model_dump_json(), v.reviewer_id.split("@")[0], to="arbiter")
        it = self._last_iteration(run).model_copy(
            update={"phase": S.REVIEWING, "verdicts": verdicts, "finding_set": review_fingerprints(verdicts)}
        )
        self.store.save_iteration(it)
        try:
            await self.hooks.after_reviews(run, verdicts)
        except Exception:  # memory write-back is best-effort
            log.exception("after_reviews hook failed for run %s", run.id)
        self._advance(run, S.ARBITRATING)

    async def _arbitrating(self, run: Run) -> None:
        verdicts = self._last_iteration(run).verdicts
        d = arbitrate(verdicts, self.cfg.budget.loop.blocking_confidence_threshold)
        self._emit(run, EventType.ARBITER_DECISION, actor="arbiter", action=d.action, reason=d.reason)
        if d.action == ArbiterAction.BACK_TO_CODER and is_oscillating(self._round_iterations(run)):
            self._escalate(run, "oscillation_detected", {"finding_set": self._last_iteration(run).finding_set})
        elif d.action == ArbiterAction.BACK_TO_CODER:
            self._save_artifact(run, "arbiter", d.model_dump_json(), "arbiter", to="coder")
            self._advance(run, S.CODING)
        elif d.action == ArbiterAction.ESCALATE:
            self._escalate(run, d.reason, d.model_dump(mode="json"))
        else:
            await self._final_gate(run, d)

    async def _final_gate(self, run: Run, d: ArbiterDecision) -> None:
        gr = await self.gate.run(self.workspace.root, GateMode.FULL)
        self._emit(run, EventType.GATE_FINISHED, actor="gate", passed=gr.passed, mode="full")
        if not gr.passed:
            self._save_artifact(run, "gate", gr.model_dump_json(), "gate", to="coder")
            self._advance(run, S.CODING)
            return
        self._escalate(run, "signoff", {"diff_ref": self._latest(run, "diff").content_ref}, on_approve=S.DONE)

    async def _agent(self, run: Run, role: str, inp: AgentInput, out: type[T]) -> AgentResult[T]:
        return (await self._agents(run, [role], inp, out))[0]

    async def _context(self, run: Run, role: str, inp: AgentInput) -> dict[str, Any]:
        try:
            return await self.hooks.context_for(run, role, inp)
        except Exception:  # an agent without memory context is better than a dead run
            log.exception("context_for hook failed for %s in run %s", role, run.id)
            return {}

    async def _agents(self, run: Run, roles: list[str], inp: AgentInput, out: type[T]) -> list[AgentResult[T]]:
        guard = BudgetGuard(run, self.cfg.budget.warn_ratio, lambda r: self._emit(
            r, EventType.BUDGET_WARNING, cost_cents=r.cost_cents, budget_cents=r.budget_cents))
        ctx = RunContext(run=run, check_budget=guard.check)
        for role in roles:
            self._emit(run, EventType.STEP_STARTED, actor=role, role=role, iteration=inp.iteration)
        files = await self.workspace.context_files()
        inputs = {r: inp.model_copy(update={"context": {**inp.context, "files": files,
                                                       **await self._context(run, r, inp)}}) for r in roles}
        if len(roles) == 1:
            results = [await self.runtime.run_agent(roles[0], inputs[roles[0]], out, ctx)]
        else:
            results = await self.runtime.run_parallel(inputs, out, ctx)
        for r in results:
            guard.record(r.usage)
            self.store.add_step(Step(
                run_id=run.id, iteration_n=inp.iteration, role=r.role, model_alias=r.alias, model=r.model,
                usage=r.usage, latency_ms=r.latency_ms, attempt_count=r.attempts,
                retry_reasons=r.retry_reasons, routing_reason=r.routing_reason,
            ))
            self._emit(run, EventType.STEP_FINISHED, actor=r.role, role=r.role, model=r.model,
                       cost_cents=r.usage.cost_cents, tokens=r.usage.tokens_in + r.usage.tokens_out,
                       tokens_in=r.usage.tokens_in, tokens_out=r.usage.tokens_out, latency_ms=r.latency_ms,
                       iteration=inp.iteration, summary=summarize(r.output))
        self.store.save_run(run)
        return results

    def _input(self, run: Run, **extra: Any) -> AgentInput:
        plan = self._latest_text(run, "plan")
        return AgentInput(
            run_id=run.id, iteration=len(self.store.iterations(run.id)) + 1, goal=run.goal,
            plan=Plan.model_validate_json(plan) if plan else None, **extra,
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
            if arb else [],
            feedback=self.blobs.get(fb.content_ref) if fb else None,
        )

    def _escalate(self, run: Run, reason: str, payload: dict[str, Any], on_approve: S = S.DONE) -> None:
        self.store.create_approval(Approval(run_id=run.id, reason=reason, payload=payload, on_approve=on_approve))
        run.paused_reason = reason
        self._emit(run, EventType.APPROVAL_REQUESTED, actor="supervisor", reason=reason, payload=payload)
        self._advance(run, S.WAITING_HUMAN)

    def _advance(self, run: Run, dst: S) -> None:
        check_transition(run.status, dst)
        src, run.status = run.status, dst
        self.store.save_run(run)
        self._emit(run, EventType.RUN_STATUS, src=src, dst=dst, terminal=dst in TERMINAL)

    def _save_artifact(self, run: Run, kind: ArtifactKind, content: str, by: str, to: str | None = None) -> None:
        ref, sha = self.blobs.put(content)
        art = Artifact(run_id=run.id, kind=kind, sha256=sha, content_ref=ref)
        self.store.add_artifact(art)
        self._emit(run, EventType.ARTIFACT_CREATED, actor=by, kind=kind, artifact_id=art.id, to=to)

    def _emit(self, run: Run, type_: EventType, actor: str = "driver", **payload: Any) -> None:
        self.bus.publish(self.store.append_event(Event(run_id=run.id, type=type_, actor=actor, payload=payload)))

    def _latest(self, run: Run, kind: ArtifactKind) -> Artifact:
        return self.store.artifacts(run.id, kind)[-1]

    def _latest_text(self, run: Run, kind: ArtifactKind) -> str | None:
        arts = self.store.artifacts(run.id, kind)
        return self.blobs.get(arts[-1].content_ref) if arts else None

    def _since_last(self, run: Run, kind: ArtifactKind) -> list[Artifact]:
        arts = self.store.artifacts(run.id)
        last = max((i for i, a in enumerate(arts) if a.kind == kind), default=-1)
        return arts[last + 1:]

    def _last_iteration(self, run: Run) -> Iteration:
        return self.store.iterations(run.id)[-1]

    def _round_iterations(self, run: Run) -> list[Iteration]:
        return self.store.iterations(run.id)[run.iteration_base:]

    def _roster(self) -> list[dict[str, str]]:
        return [{"role": r, "kind": a.kind} for r, a in self.cfg.agents.items()]
