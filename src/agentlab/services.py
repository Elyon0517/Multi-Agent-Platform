from __future__ import annotations

import asyncio
import logging
from contextlib import nullcontext
from contextvars import Context
from dataclasses import dataclass
from typing import Any

from agentlab.core.budget import BudgetGuard
from agentlab.core.memory.documents import chunk, extract_text
from agentlab.core.memory.store import (
    GLOBAL,
    PROJECT,
    Hit,
    InMemoryMemoryStore,
    MemoryItem,
    MemoryKind,
    PersistentMemoryStore,
    agent_ns,
    readable_namespaces,
)
from agentlab.core.monitor import UsageRecorder, commit_result_usage
from agentlab.core.ports import AgentRuntime, RunContext, Store
from agentlab.core.project import Project, ProjectPlan, StepStatus
from agentlab.core.schemas import AgentInput, Run, RunStatus, Severity, Verdict, new_id, utcnow

CONTEXT_HITS = 6
PROJECT_PLANNER = "project-planner"


@dataclass(frozen=True)
class DocumentSummary:
    source: str
    chunks: int
    chars: int


class KnowledgeService:
    def __init__(self, memory: InMemoryMemoryStore) -> None:
        self.memory = memory

    async def ingest(
        self, filename: str, data: bytes, project_id: str | None = None, embed: bool = False
    ) -> DocumentSummary:
        text = extract_text(filename, data)
        items = [
            MemoryItem(
                project_id=project_id,
                namespace=PROJECT if project_id else GLOBAL,
                kind=MemoryKind.DOCUMENT,
                text=c,
                source=filename,
            )
            for c in chunk(text)
        ]
        await self.memory.add(items, embed=embed)
        new_ids = {item.id for item in items}
        for old in self.memory.items_in(PROJECT if project_id else GLOBAL, project_id):
            if old.kind == MemoryKind.DOCUMENT and old.source == filename and old.id not in new_ids:
                old.valid_to = utcnow().isoformat()
                old.superseded_by = items[0].id if items else None
        self.memory.flush()
        return DocumentSummary(filename, len(items), len(text))

    def documents(self, project_id: str | None = None) -> list[DocumentSummary]:
        by_source: dict[str, list[MemoryItem]] = {}
        for i in self.memory.items_in(PROJECT if project_id else GLOBAL, project_id):
            if i.kind != MemoryKind.DOCUMENT:
                continue
            by_source.setdefault(i.source, []).append(i)
        return [DocumentSummary(s, len(items), sum(len(i.text) for i in items)) for s, items in by_source.items()]

    def delete(self, source: str, project_id: str | None = None) -> int:
        items = [
            i
            for i in self.memory.items_in(PROJECT if project_id else GLOBAL, project_id)
            if i.kind == MemoryKind.DOCUMENT and i.source == source
        ]
        for item in items:
            item.valid_to = utcnow().isoformat()
        self.memory.flush()
        return len(items)

    async def note(
        self, project_id: str | None, namespace: str, text: str, run_id: str | None = None, pinned: bool = False
    ) -> MemoryItem:
        item = MemoryItem(
            project_id=project_id,
            namespace=namespace,
            kind=MemoryKind.NOTE,
            text=text,
            source="manual" if run_id is None else "run",
            source_run_id=run_id,
            pinned=pinned,
        )
        return (await self.memory.add([item], embed=False))[0]

    async def search(
        self, project_id: str | None, role: str, query: str, k: int = CONTEXT_HITS, use_vectors: bool = False
    ) -> list[Hit]:
        return await self.memory.search(project_id, readable_namespaces(role), query, k, use_vectors=use_vectors)


class ProjectService:
    def __init__(self, store: Store | None = None) -> None:
        self.store = store
        self._projects = (
            {p.id: p for p in (Project.model_validate(row) for row in store.records("project"))} if store else {}
        )
        self.planning_attempts: list[dict[str, Any]] = store.records("planning") if store else []

    def create(self, name: str, goal: str, workspace: str, publish: bool = True) -> Project:
        p = Project(name=name, goal=goal, workspace=workspace)
        if publish:
            self.save(p)
        return p

    def get(self, project_id: str) -> Project:
        if self.store:
            self._projects = {p.id: p for p in (Project.model_validate(row) for row in self.store.records("project"))}
        return self._projects[project_id]

    def list(self) -> list[Project]:
        if self.store:
            self._projects = {p.id: p for p in (Project.model_validate(row) for row in self.store.records("project"))}
        return list(self._projects.values())

    def save(self, project: Project) -> None:
        self._projects[project.id] = project
        if self.store:
            self.store.put_record("project", project.id, project.model_dump(mode="json"))

    async def plan(
        self, project: Project, runtime: AgentRuntime, knowledge: KnowledgeService, budget_cents: float
    ) -> Project:
        hits = await knowledge.search(project.id, PROJECT_PLANNER, project.goal)
        inp = AgentInput(
            run_id=f"plan-{project.id}",
            iteration=0,
            goal=project.goal,
            context={"memory": _format_hits(hits)} if hits else {},
        )
        run = Run(
            goal=project.goal, workspace=project.workspace, project_id=project.id, budget_cents=budget_cents, max_iter=1
        )
        guard = BudgetGuard(run, 0.8, lambda _: None)
        attempt: dict[str, Any] = {
            "id": run.id,
            "project_id": project.id,
            "status": "in_flight",
            "budget_cents": budget_cents,
            "draft": project.model_dump(mode="json"),
        }

        def persist() -> None:
            attempt.update(cost_cents=run.cost_cents, tokens_in=run.tokens_in, tokens_out=run.tokens_out)
            if self.store:
                self.store.put_record("planning", run.id, attempt)

        def record(usage: Any) -> None:
            guard.record(usage)
            persist()

        def result_ready(result: Any) -> None:
            commit_result_usage(ctx, result)
            project.phases = result.output.to_phases()
            attempt["status"] = "completed"
            attempt["result"] = result.output.model_dump(mode="json")
            if self.store:
                with self.store.transaction():
                    self.save(project)
                    persist()

        def started(data: dict[str, Any]) -> str:
            identifier = new_id()
            if self.store:
                self.store.put_record(
                    "planning_call",
                    identifier,
                    {**data, "id": identifier, "planning_id": run.id, "status": "in_flight"},
                )
            return identifier

        def finished(identifier: str, data: dict[str, Any]) -> None:
            if self.store:
                previous = next(a for a in self.store.records("planning_call") if a["id"] == identifier)
                self.store.put_record("planning_call", identifier, {**previous, **data})

        persist()
        ctx = RunContext(
            run,
            check_budget=guard.check,
            record_usage=UsageRecorder(self.store, "planning", run.id, project.id, record) if self.store else record,
            reserve_budget=guard.reserve,
            release_budget=guard.release,
            on_result=result_ready,
            attempt_started=started,
            attempt_finished=finished,
            usage_transaction=self.store.transaction if self.store else nullcontext,
        )
        try:
            result = await runtime.run_agent(PROJECT_PLANNER, inp, ProjectPlan, ctx)
            if attempt["status"] != "completed":
                result_ready(result)
            attempt["budget_overrun"] = run.cost_cents > run.budget_cents
            project.phases = result.output.to_phases()
            attempt["status"] = "completed"
            self.save(project)
            return project
        except Exception as exc:
            attempt["status"] = "failed"
            attempt["error_type"] = type(exc).__name__
            raise
        finally:
            attempt.update(
                budget_cents=run.budget_cents,
                cost_cents=run.cost_cents,
                tokens_in=run.tokens_in,
                tokens_out=run.tokens_out,
            )
            self.planning_attempts.append(attempt)
            if self.store:
                self.store.put_record("planning", run.id, attempt)

    def link_run(self, project_id: str, step_id: str, run_id: str, *, locked: bool = False) -> None:
        with self.store.lock_run("project:" + project_id) if self.store and not locked else nullcontext():
            project = self.get(project_id)
            step = project.find_step(step_id)
            step.status = StepStatus.DOING
            if run_id not in step.run_ids:
                step.run_ids.append(run_id)
            self.save(project)

    def complete_run(self, run: Run) -> None:
        with self.store.lock_run("project:" + run.project_id) if self.store else nullcontext():
            try:
                project = self.get(run.project_id)
            except KeyError:
                return
            for step in project.steps():
                if run.id in step.run_ids:
                    step.status = StepStatus.DONE if run.status == RunStatus.DONE else StepStatus.BLOCKED
            self.save(project)


def _format_hits(hits: list[Hit]) -> list[dict[str, str]]:
    return [{"namespace": h.item.namespace, "source": h.item.source, "text": h.item.text} for h in hits]


class MemoryHooks:
    def __init__(self, knowledge: KnowledgeService, projects: ProjectService) -> None:
        self.knowledge = knowledge
        self.projects = projects
        self.session_services: Any = None

    def on_event(self, event: Any) -> None:
        if not self.session_services or event.run_id.startswith("thread:"):
            return
        if event.type not in {
            "step.finished",
            "gate.finished",
            "arbiter.decision",
            "approval.requested",
            "approval.decided",
        }:
            return
        if event.type == "step.finished" and event.payload.get("role", event.actor) != "planner":
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._write_progress(event)
        else:
            # Run after the driver transaction closes, without its connection context.
            loop.call_soon(self._write_progress, event, context=Context())

    def _write_progress(self, event: Any) -> None:
        try:
            from agentlab.core.conversation import Message
            from agentlab.core.schemas import Event, EventType
            from agentlab.core.session.store import append_message, get_thread

            store = self.projects.store
            if not store:
                return
            run = store.get_run(event.run_id)
            if not run.thread_id:
                return
            thread = get_thread(store, run.thread_id, run.project_id)
            key = f"event:{event.run_id}:{event.seq}"
            if any(m.id == key for m in thread.messages):
                return
            p = event.payload
            text = {
                "step.finished": "计划已完成,准备执行实现。",
                "gate.finished": "Gate 检查通过。"
                if p.get("passed")
                else f"Gate 检查未通过:{p.get('failed_at', '检查失败')}。",
                "arbiter.decision": f"评审已完成,结论:{p.get('action', '待确认')}。",
                "approval.requested": f"任务等待你的审批:{p.get('reason', '确认结果')}。",
                "approval.decided": f"已收到审批决定:{p.get('decision', '已处理')}。",
            }[event.type]
            if (event.type == "approval.requested"
                    and event.payload.get("payload", {}).get("automated_checks") == "not_run"):
                text += " 未经过自动测试。"
            payload = dict(event.payload)
            if event.type == "approval.requested":
                approval = store.pending_approval(run.id)
                if approval:
                    payload["approval_id"] = approval.id
            message = append_message(
                store,
                run.thread_id,
                run.project_id,
                Message(
                    id=key,
                    author="system",
                    kind="approval" if event.type == "approval.requested" else "progress",
                    text=text,
                    run_id=run.id,
                    payload=payload,
                ),
            )
            self.session_services.bus.publish(
                Event(
                    run_id="thread:" + run.thread_id,
                    type=EventType.MESSAGE_CREATED,
                    actor="system",
                    payload={"message": message.model_dump(mode="json")},
                )
            )
        except Exception:
            logging.getLogger(__name__).exception("conversation progress hook failed")

    async def context_for(self, run: Run, role: str, inp: AgentInput) -> dict[str, Any]:
        project_settings = (
            self.projects.get(run.project_id).settings
            if run.project_id in [p.id for p in self.projects.list()]
            else None
        )
        if inp.context.get("retrieval_settings"):
            from agentlab.core.project_config import ProjectSettings

            project_settings = ProjectSettings.model_validate(inp.context["retrieval_settings"])
        if project_settings and project_settings.retrieval == "off":
            return {}
        hits = await self.knowledge.memory.search(
            run.project_id,
            readable_namespaces(role),
            run.goal,
            project_settings.retrieval_k if project_settings else CONTEXT_HITS,
            use_vectors=bool(project_settings and project_settings.retrieval == "hybrid"),
        )
        ctx: dict[str, Any] = {"memory": _format_hits(hits)} if hits else {}
        if run.project_id in [p.id for p in self.projects.list()]:
            project = self.projects.get(run.project_id)
            done, total = project.progress()
            ctx["project"] = {"name": project.name, "goal": project.goal, "progress": f"{done}/{total}"}
        return ctx

    async def external_tools(self, role: str) -> tuple[list[dict[str, Any]], Any] | None:
        """Read-only MCP tools for run roles; tools that change outside state are only offered to Root."""
        svc = self.session_services
        if not svc:
            return None
        tools = {tool.qualified: tool for tool in await svc.mcp.tools(role) if tool.read_only}
        if not tools:
            return None

        async def execute(name: str, args: dict[str, Any]) -> Any:
            return await svc.mcp.call(tools[name], args)

        return [tool.spec for tool in tools.values()], execute

    async def after_reviews(self, run: Run, verdicts: list[Verdict]) -> None:
        pass

    async def on_waiting(self, run: Run) -> None:
        await asyncio.sleep(0)  # Flush committed progress before the summary.
        await self.summarize_run(run)

    async def on_finished(self, run: Run) -> None:
        await asyncio.sleep(0)
        store = self.projects.store
        with store.lock_run("finishing:" + run.id) if store else nullcontext():
            if store:
                try:
                    store.get_run(run.id)
                except KeyError:
                    return  # Deleted after terminal status was committed.
            try:
                self.projects.complete_run(run)
                await self.summarize_run(run)
            except Exception:
                logging.getLogger(__name__).exception("run completion bookkeeping failed for run %s", run.id)
            try:
                await self.summarize_memory(run)
            except Exception:
                logging.getLogger(__name__).exception("memory summarizer failed for run %s", run.id)

    async def summarize_memory(self, run: Run) -> None:
        import copy
        import json

        from agentlab.core.config import AppConfig
        from agentlab.core.memory.summarizer import MemoryOps, apply_ops
        from agentlab.core.schemas import normalize_text

        svc, store = self.session_services, self.projects.store
        if not svc or not store or run.status not in {RunStatus.DONE, RunStatus.CANCELLED}:
            return
        with store.lock_run("summarizer:" + run.id):
            if any(r.get("run_id") == run.id for r in store.records("summarization")):
                return
            attempt: dict[str, Any] = {"run_id": run.id, "project_id": run.project_id, "status": "started"}
            store.put_record("summarization", run.id, attempt)
            try:
                checkpoint = store.checkpoint(run.id) or {}
                cfg = AppConfig.model_validate(checkpoint["config"]) if checkpoint.get("config") else svc.cfg
                # The summarizer is a new post-run stage; old checkpoints contain its obsolete prompt.
                cfg = cfg.model_copy(update={"frozen_prompts": {
                    **cfg.frozen_prompts, "summarizer": svc.cfg.prompt("summarizer")}})
                roles = set(cfg.agents)
                feedback = [svc.blobs.get(a.content_ref)[:20000] for a in store.artifacts(run.id, "feedback")]
                feedback += [e.payload for e in store.events(run.id)
                             if e.type == "approval.decided" and e.payload.get("feedback")]
                findings: dict[tuple[str, str, str], dict[str, Any]] = {}
                last_review: dict[str, int] = {}
                for it in store.iterations(run.id):
                    for verdict in it.verdicts:
                        role = verdict.reviewer_id.split("@")[0]
                        last_review[role] = it.n
                        for finding in verdict.findings:
                            if finding.severity not in {Severity.BLOCKING, Severity.MAJOR}:
                                continue
                            key = (role, finding.file, normalize_text(finding.issue))
                            entry = findings.setdefault(key, {"role": role, "finding": finding.model_dump(mode="json"),
                                                              "iterations": []})
                            entry["iterations"].append(it.n)
                for entry in findings.values():
                    entry["recurring"] = len(set(entry["iterations"])) > 1
                    entry["resolution"] = ("absent_from_later_review" if
                        max(entry["iterations"]) < last_review[entry["role"]] else "unresolved_or_unverified")
                query = json.dumps({"feedback": feedback, "findings": list(findings.values())}, ensure_ascii=False)
                existing: list[MemoryItem] = []
                for ns in [GLOBAL, PROJECT, *(agent_ns(r) for r in roles)]:
                    hits = await self.knowledge.memory.search(run.project_id, [ns], query, 6, use_vectors=False)
                    existing.extend(h.item for h in hits)
                inp = AgentInput(run_id=run.id, iteration=0, goal="Extract durable run lessons",
                                 context={"feedback": feedback, "findings": list(findings.values()),
                                          "outcome": run.status, "termination": run.paused_reason,
                                          "approval_history": [e.payload for e in store.events(run.id)
                                                               if e.type == "approval.requested"],
                                          "roles": sorted(roles), "existing_memory": [
                                              i.model_dump(exclude={"embedding"}) for i in existing]})
                def started(data: dict[str, Any]) -> str:
                    identifier = new_id()
                    store.put_record("summarizer_call", identifier,
                                     {**data, "id": identifier, "run_id": run.id, "project_id": run.project_id,
                                      "status": "in_flight"})
                    return identifier

                def finished(identifier: str, data: dict[str, Any]) -> None:
                    previous = next(a for a in store.records("summarizer_call") if a["id"] == identifier)
                    store.put_record("summarizer_call", identifier, {**previous, **data})

                budget_run = Run(goal=inp.goal, workspace=run.workspace, project_id=run.project_id,
                                 budget_cents=25, max_iter=1)
                guard = BudgetGuard(budget_run, 0.8, lambda _: None)
                ctx = RunContext(budget_run, check_budget=guard.check,
                                 record_usage=UsageRecorder(
                                     store, "summarization", run.id, run.project_id, guard.record),
                                 reserve_budget=guard.reserve, release_budget=guard.release,
                                 usage_transaction=store.transaction,
                                 attempt_started=started, attempt_finished=finished)
                runtime = svc.runtime(checkpoint.get("options", {}).get("runtime"), cfg)
                result = await runtime.run_agent("summarizer", inp, MemoryOps, ctx)
                commit_result_usage(ctx, result)
                attempt["operations"] = result.output.model_dump(mode="json")
                # Keep the memory cache consistent if persistence of any version fails.
                memory = self.knowledge.memory
                before = copy.deepcopy(memory._items)
                persisted = copy.deepcopy(getattr(memory, "_persisted", None))
                try:
                    with store.transaction():
                        attempt["applied"] = await apply_ops(memory, run.project_id, run.id,
                                                             roles, existing, result.output)
                        attempt["status"] = "completed"
                        store.put_record("summarization", run.id, attempt)
                except Exception:
                    attempt["applied"] = []
                    memory._items = before
                    if persisted is not None and isinstance(memory, PersistentMemoryStore):
                        memory._persisted = persisted
                    raise
            except Exception as exc:
                attempt["status"] = "failed"
                attempt["error_type"] = type(exc).__name__
                store.put_record("summarization", run.id, attempt)
                raise

    async def summarize_run(self, run: Run) -> None:
        if run.thread_id and self.projects.store:
            from agentlab.core.conversation import Message
            from agentlab.core.session.store import append_message, get_thread

            store = self.projects.store
            thread = get_thread(store, run.thread_id, run.project_id)
            approval = store.pending_approval(run.id) if run.status == RunStatus.WAITING_HUMAN else None
            approval_id = approval.id if approval else None
            if not any(
                m.kind == "summary"
                and m.run_id == run.id
                and m.payload.get("status") == run.status
                and m.payload.get("approval_id") == approval_id
                for m in thread.messages
            ):
                gate_results = [e.payload for e in store.events(run.id) if e.type == "gate.finished"]
                reply = (
                    f"Run {run.status}: {run.goal}. Iterations: {len(store.iterations(run.id))}; "
                    f"cost: {run.cost_cents:.2f}c. Gate: "
                    f"{gate_results[-1].get('passed') if gate_results else 'not run'}."
                )
                sources = []
                report = approval.report if approval and approval.reason == "signoff" else None
                if report:
                    from agentlab.core.signoff import report_text

                    reply = report_text(report)
                elif self.session_services:
                    try:
                        from agentlab.core.session.service import SessionService

                        turn, _ = await SessionService(self.session_services).answer(
                            run.project_id,
                            run.thread_id,
                            f"Summarize this run and approval state using run_status. Do not create a task: {run.id}",
                            summary=True,
                        )
                        reply, sources = turn.reply, turn.sources
                    except Exception:
                        pass
                checkpoint = store.checkpoint(run.id) or {}
                if checkpoint.get("options", {}).get("gate", "unknown") is None and "未经过自动测试" not in reply:
                    reply = reply[:19970] + "\n\n未经过自动测试。"
                message = append_message(
                    store,
                    run.thread_id,
                    run.project_id,
                    Message(
                        author="assistant",
                        kind="summary",
                        text=reply[:20000],
                        sources=sources,
                        run_id=run.id,
                        payload={"status": run.status, "approval_id": approval_id,
                                 **({"report": report.model_dump(mode="json")} if report else {})},
                    ),
                )
                if self.session_services:
                    from agentlab.core.schemas import Event, EventType

                    self.session_services.bus.publish(
                        Event(
                            run_id="thread:" + run.thread_id,
                            type=EventType.MESSAGE_CREATED,
                            actor="root",
                            payload={"message": message.model_dump(mode="json")},
                        )
                    )
