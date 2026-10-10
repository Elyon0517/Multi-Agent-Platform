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
from agentlab.core.ports import RunBusy, execution_error_reason
from agentlab.core.schemas import Approval, Artifact, Event, Iteration, Run, Step
from agentlab.demo import seed_demo_workspace

log = logging.getLogger(__name__)


class CreateRun(BaseModel):
    goal: str
    thread_id: str | None = None
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
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
    def roster(project_id: str | None = None, run_id: str | None = None) -> list[dict[str, str | int]]:
        cfg = svc.cfg
        if project_id:
            try:
                project = svc.projects.get(project_id)
            except KeyError as exc:
                raise HTTPException(404, "project not found") from exc
            if project.settings:
                from agentlab.core.project_config import project_config

                cfg = project_config(cfg, project.settings)
        if run_id:
            run = get_run(run_id)
            if project_id and run.project_id != project_id:
                raise HTTPException(422, "run belongs to another project")
            checkpoint = svc.store.checkpoint(run_id)
            if checkpoint:
                from agentlab.core.config import AppConfig

                cfg = AppConfig.model_validate(checkpoint["config"])
        policy = cfg.model_policy.roles
        aliases = cfg.models.aliases
        out: list[dict[str, str | int]] = []
        for r, a in svc.cfg.agents.items():
            alias = policy[r].primary if r in policy else ""
            m = aliases[alias] if alias else None
            out.append(
                {
                    "role": r,
                    "kind": a.kind,
                    "alias": alias,
                    "model": m.model if m else "",
                    "ctx_window": m.ctx_window if m else 0,
                }
            )
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
        conversation = None
        new_conversation = False
        if body.thread_id:
            from agentlab.core.conversation import Conversation
            conversation = next((Conversation.model_validate(t) for t in svc.store.records("thread")
                                 if t["id"] == body.thread_id and t["project_id"] == body.project_id), None)
            if conversation is None:
                raise HTTPException(404, "conversation not found in this project")
            if len(conversation.messages) >= 998:
                raise HTTPException(409, "conversation is full; start a new conversation")
        elif body.project_id:
            from agentlab.core.conversation import Conversation
            conversation = Conversation(project_id=body.project_id, title=body.goal.strip()[:80] or "New conversation")
            body.thread_id = conversation.id
            new_conversation = True
        if not body.goal.strip() or len(body.goal) > 20000:
            raise HTTPException(422, "goal must contain 1 to 20000 characters")
        ws = (
            Path(body.workspace)
            if body.workspace
            else seed_demo_workspace(Path(tempfile.mkdtemp(prefix="agentlab-demo-")))
        )
        try:
            driver = svc.driver(ws, body.runtime, body.language, body.project_id)
            if conversation:
                driver.recovery_options["conversation"] = [
                    m.model_dump(mode="json") for m in conversation.messages[-20:]
                ]
        except (MissingGatewayConfig, NoGateDetected) as e:
            raise HTTPException(400, f"{type(e).__name__}: {e}") from e

        def record_conversation(run: Run) -> None:
            if not conversation:
                return
            from agentlab.core.conversation import Conversation, Message

            with svc.store.lock_run("thread:" + conversation.id):
                latest = conversation if new_conversation else next(
                    Conversation.model_validate(t) for t in svc.store.records("thread") if t["id"] == conversation.id
                )
                if len(latest.messages) >= 998:
                    raise HTTPException(409, "conversation is full; start a new conversation")
                latest.messages.append(Message(author="user", text=body.goal, run_id=run.id))
                svc.store.put_record("thread", latest.id, latest.model_dump(mode="json"))

        try:
            await driver.workspace.ensure_repo()  # type: ignore[attr-defined]
            run = await driver.create_async(
                body.goal, project_id=body.project_id or "default", thread_id=body.thread_id,
                on_create=record_conversation
            )
        except RunBusy as exc:
            driver.workspace.close()  # type: ignore[attr-defined]
            raise HTTPException(409, str(exc)) from exc
        except HTTPException:
            driver.workspace.close()  # type: ignore[attr-defined]
            raise
        except Exception as exc:
            driver.workspace.close()  # type: ignore[attr-defined]
            reason = execution_error_reason(exc)
            status = 422 if reason in {"workspace_unreadable", "workspace_escape", "workspace_root_required"} else 503
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
    def list_runs(project_id: str | None = None) -> list[Run]:
        return [r for r in svc.store.list_runs() if project_id is None or r.project_id == project_id]

    @app.get("/runs/{run_id}", response_model=RunDetail)
    def run_detail(run_id: str) -> RunDetail:
        return RunDetail(
            run=get_run(run_id),
            iterations=svc.store.iterations(run_id),
            steps=svc.store.steps(run_id),
            artifacts=svc.store.artifacts(run_id),
            pending_approval=svc.store.pending_approval(run_id),
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
            try:
                driver = svc.restore_driver(run_id)
                drivers[run_id] = driver
            except Exception as exc:
                raise HTTPException(409, f"recovery failed: {type(exc).__name__}") from exc
        try:
            run = driver.decide(
                run_id, body.decision, body.feedback, budget_cents=body.budget_cents, max_iter=body.max_iter
            )
        except (ValueError, MissingGatewayConfig, RunBusy) as e:
            raise HTTPException(409, str(e)) from e
        spawn(driver, run_id)
        return run

    @app.post("/runs/{run_id}/resume", response_model=Run)
    async def resume(run_id: str) -> Run:
        get_run(run_id)
        try:
            driver = svc.restore_driver(run_id)
            drivers[run_id] = driver
            return await driver.run(run_id)
        except Exception as exc:
            raise HTTPException(409, f"resume failed: {type(exc).__name__}") from exc

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
