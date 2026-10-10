from __future__ import annotations

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
from agentlab.core.ports import AgentRuntime, RunContext
from agentlab.core.project import Project, ProjectPlan, StepStatus
from agentlab.core.schemas import AgentInput, Run, RunStatus, Severity, Verdict, utcnow

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

    async def ingest(self, filename: str, data: bytes) -> DocumentSummary:
        text = extract_text(filename, data)
        items = [MemoryItem(project_id=None, namespace=GLOBAL, kind=MemoryKind.DOCUMENT, text=c, source=filename)
                 for c in chunk(text)]
        await self.memory.add(items)
        new_ids = {item.id for item in items}
        for old in self.memory.items_in(GLOBAL):
            if old.source == filename and old.id not in new_ids:
                old.valid_to = utcnow().isoformat()
                old.superseded_by = items[0].id if items else None
        return DocumentSummary(filename, len(items), len(text))

    def documents(self) -> list[DocumentSummary]:
        by_source: dict[str, list[MemoryItem]] = {}
        for i in self.memory.items_in(GLOBAL):
            by_source.setdefault(i.source, []).append(i)
        return [DocumentSummary(s, len(items), sum(len(i.text) for i in items)) for s, items in by_source.items()]

    def delete(self, source: str) -> int:
        return self.memory.delete_source(GLOBAL, source)

    async def note(self, project_id: str | None, namespace: str, text: str, run_id: str | None = None,
                   pinned: bool = False) -> MemoryItem:
        item = MemoryItem(project_id=project_id, namespace=namespace, kind=MemoryKind.NOTE, text=text,
                          source="manual" if run_id is None else "run", source_run_id=run_id, pinned=pinned)
        return (await self.memory.add([item]))[0]

    async def search(self, project_id: str | None, role: str, query: str, k: int = CONTEXT_HITS) -> list[Hit]:
        return await self.memory.search(project_id, readable_namespaces(role), query, k)


class ProjectService:
    def __init__(self) -> None:
        self._projects: dict[str, Project] = {}
        self.planning_attempts: list[dict[str, Any]] = []

    def create(self, name: str, goal: str, workspace: str, publish: bool = True) -> Project:
        p = Project(name=name, goal=goal, workspace=workspace)
        if publish:
            self._projects[p.id] = p
        return p

    def get(self, project_id: str) -> Project:
        return self._projects[project_id]

    def list(self) -> list[Project]:
        return list(self._projects.values())

    def save(self, project: Project) -> None:
        self._projects[project.id] = project

    async def plan(self, project: Project, runtime: AgentRuntime, knowledge: KnowledgeService,
                   budget_cents: float) -> Project:
        hits = await knowledge.search(project.id, PROJECT_PLANNER, project.goal)
        inp = AgentInput(run_id=f"plan-{project.id}", iteration=0, goal=project.goal,
                         context={"memory": _format_hits(hits)} if hits else {})
        run = Run(goal=project.goal, workspace=project.workspace, project_id=project.id,
                  budget_cents=budget_cents, max_iter=1)
        guard = BudgetGuard(run, 0.8, lambda _: None)
        ctx = RunContext(run, check_budget=guard.check, record_usage=guard.record,
                         reserve_budget=guard.reserve, release_budget=guard.release)
        attempt: dict[str, Any] = {"id": run.id, "project_id": project.id, "status": "failed"}
        try:
            result = await runtime.run_agent(PROJECT_PLANNER, inp, ProjectPlan, ctx)
            if not result.usage_recorded:
                guard.record(result.usage)
            attempt["budget_overrun"] = run.cost_cents > run.budget_cents
            project.phases = result.output.to_phases()
            attempt["status"] = "completed"
            return project
        except Exception as exc:
            attempt["error_type"] = type(exc).__name__
            raise
        finally:
            attempt.update(budget_cents=run.budget_cents, cost_cents=run.cost_cents,
                           tokens_in=run.tokens_in, tokens_out=run.tokens_out)
            self.planning_attempts.append(attempt)

    def link_run(self, project_id: str, step_id: str, run_id: str) -> None:
        step = self.get(project_id).find_step(step_id)
        step.status = StepStatus.DOING
        step.run_ids.append(run_id)

    def complete_run(self, run: Run) -> None:
        if run.project_id not in self._projects:
            return
        for step in self.get(run.project_id).steps():
            if run.id in step.run_ids:
                step.status = StepStatus.DONE if run.status == RunStatus.DONE else StepStatus.BLOCKED


def _format_hits(hits: list[Hit]) -> list[dict[str, str]]:
    return [{"namespace": h.item.namespace, "source": h.item.source, "text": h.item.text} for h in hits]


class MemoryHooks:
    def __init__(self, knowledge: KnowledgeService, projects: ProjectService) -> None:
        self.knowledge = knowledge
        self.projects = projects

    async def context_for(self, run: Run, role: str, inp: AgentInput) -> dict[str, Any]:
        hits = await self.knowledge.search(run.project_id, role, run.goal)
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
        outcome = "approved" if run.status == RunStatus.DONE else f"ended as {run.status}"
        await self.knowledge.note(run.project_id, PROJECT, f"Run {run.id} '{run.goal}' {outcome}.", run.id)
