from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from agentlab.bootstrap import MissingGatewayConfig, Services
from agentlab.core.budget import BudgetExceeded
from agentlab.core.config import AliasCfg
from agentlab.core.conversation import Conversation
from agentlab.core.memory.documents import UnsupportedDocument
from agentlab.core.memory.store import GLOBAL, PROJECT, Hit, MemoryItem, agent_ns
from agentlab.core.ports import RunBusy
from agentlab.core.project import Project, ProjectPhase, StepStatus
from agentlab.core.project_config import Binding, ProjectSettings, project_config, validate_settings
from agentlab.core.schemas import Strict
from agentlab.secrets import EDITABLE, SettingView
from agentlab.services import DocumentSummary


class ModelCatalog(BaseModel):
    aliases: dict[str, AliasCfg]
    roles: dict[str, Binding]
    root_alias: str


class MemoryStatus(BaseModel):
    items: int
    embedded: int
    embedding_model: str | None
    embedding_ready: bool
    embedding_configured: bool
    last_error: str | None
    embedding_backend: str | None
    embedding_dimensions: int | None
    compatible_embedded: int
    rerank_model: str | None
    rerank_ready: bool
    rerank_error: str | None


class ProfileLoader(yaml.SafeLoader):
    """YAML 1.2-style booleans: retrieval=off and model aliases stay strings."""


ProfileLoader.yaml_implicit_resolvers = {
    key: [(tag, pattern) for tag, pattern in resolvers if tag != "tag:yaml.org,2002:bool"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
ProfileLoader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$", re.I), list("tTfF"))

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class SettingsBody(BaseModel):
    values: dict[str, str]


class NoteBody(BaseModel):
    scope: Literal["global", "project", "agent"]
    text: str = Field(min_length=1, max_length=20000)
    project_id: str | None = None
    role: str | None = None
    pinned: bool = False


class SearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    role: str = "planner"
    project_id: str | None = None
    k: int = Field(default=8, ge=1, le=20)


class CreateProject(Strict):
    settings: ProjectSettings | None = None
    name: str
    goal: str
    workspace: str
    runtime: str | None = None
    budget_cents: float | None = Field(default=None, gt=0)


class ProfileBody(Strict):
    yaml_text: str = Field(max_length=100000)


class PatchStep(BaseModel):
    status: StepStatus


def _namespace(scope: str, role: str | None) -> str:
    if scope in (GLOBAL, PROJECT):
        return scope
    if scope == "agent" and role:
        return agent_ns(role)
    raise HTTPException(422, "scope must be global, project, or agent (with role)")


def build_router(svc: Services) -> APIRouter:
    r = APIRouter()

    def validate_scope(project_id: str | None, scope: str = "global", role: str | None = None) -> None:
        if scope != "global" and not project_id:
            raise HTTPException(422, "select a project for private memory")
        if project_id:
            try:
                svc.projects.get(project_id)
            except KeyError as exc:
                raise HTTPException(404, "project not found") from exc
        if role and role not in svc.cfg.agents:
            raise HTTPException(422, "unknown agent role")

    @r.get("/models", response_model=ModelCatalog)
    def models() -> dict[str, Any]:
        return {
            "aliases": {a: c.model_dump(mode="json") for a, c in svc.cfg.models.aliases.items()},
            "roles": {
                r: {"alias": p.primary, "task": f"Perform {r}"}
                for r, p in svc.cfg.model_policy.roles.items()
                if r not in {"root", "supervisor", "project-planner"}
            },
            "root_alias": svc.cfg.model_policy.roles["supervisor"].primary,
        }

    @r.put("/projects/{project_id}/settings", response_model=Project)
    def update_project_settings(project_id: str, body: ProjectSettings) -> Project:
        validate_scope(project_id)
        try:
            validate_settings(body, svc.cfg)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        with svc.store.lock_run("project:" + project_id):
            project = svc.projects.get(project_id)
            project.settings = body
            svc.projects.save(project)
            return project

    @r.get("/projects/{project_id}/profile", response_class=PlainTextResponse)
    def export_profile(project_id: str) -> str:
        validate_scope(project_id)
        settings = svc.projects.get(project_id).settings or ProjectSettings()
        return yaml.safe_dump(settings.model_dump(mode="json"), sort_keys=False, allow_unicode=True)

    @r.put("/projects/{project_id}/profile", response_model=Project)
    def import_profile(project_id: str, body: ProfileBody) -> Project:
        try:
            settings = ProjectSettings.model_validate(yaml.load(body.yaml_text, Loader=ProfileLoader))
        except (ValueError, yaml.YAMLError) as exc:
            raise HTTPException(422, "invalid project settings YAML") from exc
        return update_project_settings(project_id, settings)

    @r.get("/projects/{project_id}/usage")
    def project_usage(project_id: str) -> dict[str, Any]:
        validate_scope(project_id)
        runs = [run for run in svc.store.list_runs() if run.project_id == project_id]
        turns = [turn for turn in svc.store.records("root_turn") if turn.get("project_id") == project_id]
        run_cost = sum(run.cost_cents for run in runs)
        conversation_cost = sum(float(turn.get("cost_cents", 0)) for turn in turns)
        return {"run_cost_cents": run_cost, "conversation_cost_cents": conversation_cost,
                "cost_cents": run_cost + conversation_cost,
                "tokens_in": sum(run.tokens_in for run in runs) + sum(int(t.get("tokens_in", 0)) for t in turns),
                "tokens_out": sum(run.tokens_out for run in runs) + sum(int(t.get("tokens_out", 0)) for t in turns)}

    @r.get("/projects/{project_id}/threads", response_model=list[Conversation])
    def threads(project_id: str) -> list[Conversation]:
        validate_scope(project_id)
        return [Conversation.model_validate(t) for t in svc.store.records("thread") if t["project_id"] == project_id]

    @r.post("/projects/{project_id}/threads", response_model=Conversation)
    def create_thread(project_id: str, body: dict[str, str]) -> Conversation:
        validate_scope(project_id)
        try:
            thread = Conversation(project_id=project_id, title=body.get("title", "New conversation"))
        except ValueError as exc:
            raise HTTPException(422, "invalid conversation title") from exc
        svc.store.put_record("thread", thread.id, thread.model_dump(mode="json"))
        return thread

    @r.get("/settings", response_model=list[SettingView])
    def get_settings() -> list[SettingView]:
        return svc.setting_views()

    @r.put("/settings", response_model=list[SettingView])
    def put_settings(body: SettingsBody) -> list[SettingView]:
        values = {k: v.strip() for k, v in body.values.items() if v.strip()}
        try:
            svc.env.update(values)
        except (KeyError, ValueError) as e:
            raise HTTPException(422, f"{e}; editable: {list(EDITABLE)}") from e
        svc.knowledge.memory.verified = False
        svc.knowledge.memory.last_error = None
        return svc.setting_views()

    @r.get("/knowledge", response_model=list[DocumentSummary])
    def list_docs(project_id: str | None = None) -> list[dict[str, Any]]:
        validate_scope(project_id)
        return [d.__dict__ for d in svc.knowledge.documents(project_id)]

    @r.post("/knowledge", response_model=DocumentSummary)
    async def upload(file: UploadFile, project_id: str | None = None) -> dict[str, Any]:
        validate_scope(project_id)
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "file larger than 20 MB")
        try:
            settings = svc.projects.get(project_id).settings if project_id else None
            return (
                await svc.knowledge.ingest(
                    file.filename or "upload",
                    data,
                    project_id,
                    embed=project_id is None or bool(settings and settings.retrieval == "hybrid"),
                )
            ).__dict__
        except UnsupportedDocument as e:
            raise HTTPException(422, str(e)) from e

    @r.delete("/knowledge/{source}")
    def delete_doc(source: str, project_id: str | None = None) -> dict[str, int]:
        validate_scope(project_id)
        return {"deleted": svc.knowledge.delete(source, project_id)}

    @r.get("/memory", response_model=list[MemoryItem])
    def list_memory(scope: str, project_id: str | None = None, role: str | None = None) -> list[MemoryItem]:
        validate_scope(project_id, scope, role)
        items = svc.knowledge.memory.items_in(_namespace(scope, role), project_id)
        return [i.model_copy(update={"embedding": None}) for i in items]

    @r.post("/memory", response_model=MemoryItem)
    async def add_memory(body: NoteBody) -> MemoryItem:
        validate_scope(body.project_id, body.scope, body.role)
        item = await svc.knowledge.note(
            body.project_id, _namespace(body.scope, body.role), body.text, pinned=body.pinned
        )
        return item.model_copy(update={"embedding": None})

    @r.post("/memory/search", response_model=list[Hit])
    async def search_memory(body: SearchBody) -> list[Hit]:
        validate_scope(body.project_id, "project" if body.project_id else "global", body.role)
        settings = svc.projects.get(body.project_id).settings if body.project_id else None
        if settings and settings.retrieval == "off":
            return []
        hits = await svc.knowledge.search(
            body.project_id,
            body.role,
            body.query,
            settings.retrieval_k if settings else body.k,
            use_vectors=bool(settings and settings.retrieval == "hybrid"),
        )
        return [h.model_copy(update={"item": h.item.model_copy(update={"embedding": None})}) for h in hits]

    @r.post("/memory/probe", response_model=MemoryStatus)
    async def probe_embedding() -> dict[str, object]:
        await svc.knowledge.memory._embed(["embedding connectivity test"])
        return svc.knowledge.memory.stats()

    @r.post("/knowledge/reindex", response_model=MemoryStatus)
    async def reindex_global() -> dict[str, object]:
        if not svc.knowledge.memory._can_embed():
            raise HTTPException(422, "embedding provider unavailable")
        await svc.knowledge.memory.add(svc.knowledge.memory.items_in(GLOBAL))
        return svc.knowledge.memory.stats()

    @r.post("/projects/{project_id}/knowledge/reindex", response_model=MemoryStatus)
    async def reindex(project_id: str) -> dict[str, object]:
        validate_scope(project_id)
        settings = svc.projects.get(project_id).settings
        if not settings or settings.retrieval != "hybrid":
            raise HTTPException(422, "enable hybrid retrieval for this project first")
        if not svc.knowledge.memory._can_embed():
            raise HTTPException(422, "embedding provider unavailable")
        items = [
            i
            for namespace in [PROJECT, *(agent_ns(role) for role in svc.cfg.agents)]
            for i in svc.knowledge.memory.items_in(namespace, project_id)
        ]
        # Preserve ids and history; refreshed embeddings are persisted with the same chunks.
        await svc.knowledge.memory.add(items)
        return svc.knowledge.memory.stats()

    @r.get("/memory/status", response_model=MemoryStatus)
    def memory_status() -> dict[str, object]:
        return svc.knowledge.memory.stats()

    @r.get("/project-planning")
    def planning_attempts() -> list[dict[str, Any]]:
        return svc.projects.planning_attempts

    @r.get("/projects", response_model=list[Project])
    def list_projects() -> list[Project]:
        return svc.projects.list()

    @r.post("/projects", response_model=Project)
    async def create_project(body: CreateProject) -> Project:
        try:
            with svc.store.lock_run("project-creation"):
                return await create_project_locked(body)
        except RunBusy as exc:
            raise HTTPException(409, "another project is being created; try again after it finishes") from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise HTTPException(503, {"reason": "workspace_check_failed", "error_type": type(exc).__name__}) from exc

    async def create_project_locked(body: CreateProject) -> Project:
        workspace = Path(body.workspace).expanduser().resolve()
        if not workspace.is_dir():
            raise HTTPException(422, "workspace must be an existing directory")
        check = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "--show-toplevel"], capture_output=True, timeout=30
        )
        if check.returncode == 0 and Path(check.stdout.decode().strip()).resolve() != workspace:
            raise HTTPException(422, "workspace must point to the repository root")
        for existing in svc.projects.list():
            other = Path(existing.workspace).resolve()
            if workspace == other or workspace in other.parents or other in workspace.parents:
                raise HTTPException(409, "workspace overlaps another project; use an independent worktree")
        if not body.name.strip() or not body.goal.strip():
            raise HTTPException(422, "name and goal are required")
        settings = body.settings or ProjectSettings()
        try:
            cfg = project_config(svc.cfg, settings)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        project = svc.projects.create(body.name.strip(), body.goal.strip(), str(workspace), publish=False)
        project.settings = settings
        try:
            await svc.projects.plan(
                project,
                svc.runtime(body.runtime, cfg),
                svc.knowledge,
                body.budget_cents or cfg.budget.default_run_budget_cents,
            )
        except MissingGatewayConfig as e:
            raise HTTPException(400, type(e).__name__) from e
        except BudgetExceeded as e:
            raise HTTPException(409, "project planning budget exceeded") from e
        except Exception as e:
            raise HTTPException(502, f"project planning failed: {type(e).__name__}") from e
        svc.projects.save(project)
        return project

    @r.get("/projects/{project_id}", response_model=Project)
    def get_project(project_id: str) -> Project:
        try:
            return svc.projects.get(project_id)
        except KeyError as e:
            raise HTTPException(404, "project not found") from e

    @r.put("/projects/{project_id}/phases", response_model=Project)
    def replace_phases(project_id: str, phases: list[ProjectPhase]) -> Project:
        project = get_project(project_id)
        project.phases = phases
        svc.projects.save(project)
        return project

    @r.patch("/projects/{project_id}/steps/{step_id}", response_model=Project)
    def patch_step(project_id: str, step_id: str, body: PatchStep) -> Project:
        project = get_project(project_id)
        try:
            project.find_step(step_id).status = body.status
        except StopIteration as e:
            raise HTTPException(404, "step not found") from e
        svc.projects.save(project)
        return project

    return r
