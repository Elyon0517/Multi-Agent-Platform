from __future__ import annotations

import asyncio
import logging
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from agentlab.adapters.gates.config_gate import NoGateDetected
from agentlab.adapters.store.memory import NotFound
from agentlab.api.knowledge import build_router
from agentlab.bootstrap import MissingGatewayConfig, Services, build_services
from agentlab.core.loop.driver import Decision, Driver
from agentlab.core.ports import execution_error_reason
from agentlab.core.schemas import Approval, Artifact, Event, Iteration, Run, Step
from agentlab.demo import seed_demo_workspace

log = logging.getLogger(__name__)


class CreateRun(BaseModel):
    goal: str
    workspace: str | None = None
    runtime: str | None = None
    language: str | None = None
    project_id: str | None = None
    step_id: str | None = None


class DecideBody(BaseModel):
    decision: Decision
    feedback: str | None = None
    budget_cents: float | None = None
    max_iter: int | None = None


class RunDetail(BaseModel):
    run: Run
    iterations: list[Iteration]
    steps: list[Step]
    artifacts: list[Artifact]
    pending_approval: Approval | None


def create_app(svc: Services | None = None) -> FastAPI:
    svc = svc or build_services()
    drivers: dict[str, Driver] = {}
    tasks: set[asyncio.Task[Run]] = set()
    app = FastAPI(title="Agent Converge", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["*"])
    app.include_router(build_router(svc))

    def spawn(driver: Driver, run_id: str) -> None:
        task = asyncio.create_task(driver.run(run_id))
        tasks.add(task)
        def finished(done: asyncio.Task[Run]) -> None:
            tasks.discard(done)
            if not done.cancelled() and (error := done.exception()) is not None:
                log.error("background run %s failed: %s", run_id, type(error).__name__)

        task.add_done_callback(finished)

    def get_run(run_id: str) -> Run:
        try:
            return svc.store.get_run(run_id)
        except NotFound as e:
            raise HTTPException(404, f"run {run_id} not found") from e

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "agents": sorted(svc.cfg.agents)}

    @app.get("/roster")
    def roster() -> list[dict[str, str | int]]:
        policy = svc.cfg.model_policy.roles
        aliases = svc.cfg.models.aliases
        out: list[dict[str, str | int]] = []
        for r, a in svc.cfg.agents.items():
            alias = policy[r].primary if r in policy else ""
            m = aliases[alias] if alias else None
            out.append({"role": r, "kind": a.kind, "alias": alias, "model": m.model if m else "",
                        "ctx_window": m.ctx_window if m else 0})
        return out

    @app.post("/runs", response_model=Run)
    async def create_run(body: CreateRun) -> Run:
        if body.project_id:
            try:
                project = svc.projects.get(body.project_id)
                if body.step_id:
                    project.find_step(body.step_id)
            except (KeyError, StopIteration) as e:
                raise HTTPException(404, "project or step not found") from e
            if body.workspace and Path(body.workspace).resolve() != Path(project.workspace).resolve():
                raise HTTPException(422, "workspace must match the selected project")
            body.workspace = project.workspace
        elif body.step_id:
            raise HTTPException(422, "step_id requires project_id")
        ws = Path(body.workspace) if body.workspace else seed_demo_workspace(
            Path(tempfile.mkdtemp(prefix="agentlab-demo-")))
        try:
            driver = svc.driver(ws, body.runtime, body.language)
        except (MissingGatewayConfig, NoGateDetected) as e:
            raise HTTPException(400, f"{type(e).__name__}: {e}") from e
        try:
            await driver.workspace.ensure_repo()  # type: ignore[attr-defined]
            run = await driver.create_async(body.goal, project_id=body.project_id or "default")
        except Exception as exc:
            driver.workspace.close()  # type: ignore[attr-defined]
            reason = execution_error_reason(exc)
            status = 422 if reason in {"workspace_unreadable", "workspace_escape"} else 503
            raise HTTPException(status, {"reason": reason, "error_type": type(exc).__name__}) from exc
        if body.project_id and body.step_id:
            try:
                svc.projects.link_run(body.project_id, body.step_id, run.id)
            except (KeyError, StopIteration) as e:
                raise HTTPException(404, "project or step not found") from e
        drivers[run.id] = driver
        spawn(driver, run.id)
        return run

    @app.get("/runs", response_model=list[Run])
    def list_runs() -> list[Run]:
        return svc.store.list_runs()

    @app.get("/runs/{run_id}", response_model=RunDetail)
    def run_detail(run_id: str) -> RunDetail:
        return RunDetail(
            run=get_run(run_id), iterations=svc.store.iterations(run_id), steps=svc.store.steps(run_id),
            artifacts=svc.store.artifacts(run_id), pending_approval=svc.store.pending_approval(run_id),
        )

    @app.get("/artifacts/{run_id}/{artifact_id}")
    def artifact_content(run_id: str, artifact_id: str) -> dict[str, str]:
        art = next((a for a in svc.store.artifacts(run_id) if a.id == artifact_id), None)
        if art is None:
            raise HTTPException(404, "artifact not found")
        return {"kind": art.kind, "content": svc.blobs.get(art.content_ref)}

    @app.post("/runs/{run_id}/decision", response_model=Run)
    async def decide(run_id: str, body: DecideBody) -> Run:
        get_run(run_id)
        driver = drivers.get(run_id)
        if driver is None:
            raise HTTPException(409, "run not owned by this daemon")
        try:
            run = driver.decide(run_id, body.decision, body.feedback, budget_cents=body.budget_cents,
                                max_iter=body.max_iter)
        except (ValueError, MissingGatewayConfig) as e:
            raise HTTPException(409, str(e)) from e
        spawn(driver, run_id)
        return run

    @app.get("/runs/{run_id}/events")
    async def events(run_id: str, request: Request, after: int = 0) -> EventSourceResponse:
        get_run(run_id)
        try:
            last = int(request.headers.get("last-event-id", "0"))
            if after < 0 or last < 0:
                raise ValueError
            after = max(after, last)
        except ValueError as exc:
            raise HTTPException(422, "invalid event cursor") from exc

        async def stream() -> AsyncIterator[dict[str, str]]:
            live = svc.bus.subscribe(run_id)  # eager registration before the history snapshot
            try:
                seen = after
                for event in svc.store.events(run_id, after):
                    seen = event.seq
                    yield _sse(event)
                async for event in live:
                    if event.seq > seen:
                        seen = event.seq
                        yield _sse(event)
            finally:
                await live.aclose()

        return EventSourceResponse(stream())

    return app


def _sse(e: Event) -> dict[str, str]:
    return {"id": str(e.seq), "event": e.type.value, "data": e.model_dump_json()}
