from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

from agentlab.bootstrap import MissingGatewayConfig, Services
from agentlab.core.memory.documents import UnsupportedDocument
from agentlab.core.memory.store import GLOBAL, PROJECT, Hit, MemoryItem, agent_ns
from agentlab.core.project import Project, ProjectPhase, StepStatus
from agentlab.secrets import EDITABLE, SettingView

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class SettingsBody(BaseModel):
    values: dict[str, str]


class NoteBody(BaseModel):
    scope: str
    text: str
    project_id: str | None = None
    role: str | None = None
    pinned: bool = False


class SearchBody(BaseModel):
    query: str
    role: str = "planner"
    project_id: str | None = None
    k: int = 8


class CreateProject(BaseModel):
    name: str
    goal: str
    workspace: str
    runtime: str | None = None


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
        return svc.setting_views()

    @r.get("/knowledge")
    def list_docs() -> list[dict[str, Any]]:
        return [d.__dict__ for d in svc.knowledge.documents()]

    @r.post("/knowledge")
    async def upload(file: UploadFile) -> dict[str, Any]:
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "file larger than 20 MB")
        try:
            return (await svc.knowledge.ingest(file.filename or "upload", data)).__dict__
        except UnsupportedDocument as e:
            raise HTTPException(422, str(e)) from e

    @r.delete("/knowledge/{source}")
    def delete_doc(source: str) -> dict[str, int]:
        return {"deleted": svc.knowledge.delete(source)}

    @r.get("/memory", response_model=list[MemoryItem])
    def list_memory(scope: str, project_id: str | None = None, role: str | None = None) -> list[MemoryItem]:
        items = svc.knowledge.memory.items_in(_namespace(scope, role), project_id)
        return [i.model_copy(update={"embedding": None}) for i in items]

    @r.post("/memory", response_model=MemoryItem)
    async def add_memory(body: NoteBody) -> MemoryItem:
        item = await svc.knowledge.note(body.project_id, _namespace(body.scope, body.role), body.text,
                                        pinned=body.pinned)
        return item.model_copy(update={"embedding": None})

    @r.post("/memory/search", response_model=list[Hit])
    async def search_memory(body: SearchBody) -> list[Hit]:
        hits = await svc.knowledge.search(body.project_id, body.role, body.query, body.k)
        return [h.model_copy(update={"item": h.item.model_copy(update={"embedding": None})}) for h in hits]

    @r.get("/memory/status")
    def memory_status() -> dict[str, object]:
        return svc.knowledge.memory.stats()

    @r.get("/projects", response_model=list[Project])
    def list_projects() -> list[Project]:
        return svc.projects.list()

    @r.post("/projects", response_model=Project)
    async def create_project(body: CreateProject) -> Project:
        project = svc.projects.create(body.name, body.goal, body.workspace)
        try:
            await svc.projects.plan(project, svc.runtime(body.runtime), svc.knowledge,
                                    svc.cfg.budget.default_run_budget_cents)
        except MissingGatewayConfig as e:
            raise HTTPException(400, f"{type(e).__name__}: {e}") from e
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
        return project

    @r.patch("/projects/{project_id}/steps/{step_id}", response_model=Project)
    def patch_step(project_id: str, step_id: str, body: PatchStep) -> Project:
        project = get_project(project_id)
        try:
            project.find_step(step_id).status = body.status
        except StopIteration as e:
            raise HTTPException(404, "step not found") from e
        return project

    return r
