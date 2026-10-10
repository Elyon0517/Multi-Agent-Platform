from __future__ import annotations

import json
import logging
from contextlib import nullcontext
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
    agent_ns,
    readable_namespaces,
)
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
            if not result.usage_recorded:
                record(result.usage)
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
            record_usage=record,
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

    def link_run(self, project_id: str, step_id: str, run_id: str) -> None:
        with self.store.lock_run("project:" + project_id) if self.store else nullcontext():
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
            "run.status",
        }:
            return
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
            text = f"{event.type}: {json.dumps(event.payload, ensure_ascii=False)}"[:20000]
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

    async def after_reviews(self, run: Run, verdicts: list[Verdict]) -> None:
        for v in verdicts:
            role = v.reviewer_id.split("@")[0]
            hard = [f for f in v.findings if f.severity in (Severity.BLOCKING, Severity.MAJOR)]
            if hard:
                text = "; ".join(f"{f.file}: {f.issue}" for f in hard[:5])
                await self.knowledge.note(run.project_id, agent_ns(role), f"Flagged in run {run.id}: {text}", run.id)

    async def on_finished(self, run: Run) -> None:
        self.projects.complete_run(run)
        if run.thread_id and self.projects.store:
            from agentlab.core.conversation import Message
            from agentlab.core.session.store import append_message, get_thread

            store = self.projects.store
            thread = get_thread(store, run.thread_id, run.project_id)
            if not any(m.kind == "summary" and m.run_id == run.id for m in thread.messages):
                gate_results = [e.payload for e in store.events(run.id) if e.type == "gate.finished"]
                reply = (
                    f"Run {run.status}: {run.goal}. Iterations: {len(store.iterations(run.id))}; "
                    f"cost: {run.cost_cents:.2f}c. Gate: "
                    f"{gate_results[-1].get('passed') if gate_results else 'not run'}."
                )
                sources = []
                if self.session_services:
                    try:
                        from agentlab.core.session.service import SessionService

                        turn, _ = await SessionService(self.session_services).answer(
                            run.project_id,
                            run.thread_id,
                            f"Summarize this completed run using run_status. Do not create a task: {run.id}",
                            summary=True,
                        )
                        reply, sources = turn.reply, turn.sources
                    except Exception:
                        pass
                message = append_message(
                    store,
                    run.thread_id,
                    run.project_id,
                    Message(author="assistant", kind="summary", text=reply[:20000], sources=sources, run_id=run.id),
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
        outcome = "approved" if run.status == RunStatus.DONE else f"ended as {run.status}"
        text = f"Run {run.id} '{run.goal}' {outcome}."
        if not any(
            i.source_run_id == run.id and i.text == text
            for i in self.knowledge.memory.items_in(PROJECT, run.project_id)
        ):
            await self.knowledge.note(run.project_id, PROJECT, text, run.id)
