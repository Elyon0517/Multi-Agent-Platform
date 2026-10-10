from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from agentlab.adapters.store.memory import NotFound
from agentlab.api.knowledge import build_router
from agentlab.bootstrap import MissingGatewayConfig, Services, build_services
from agentlab.core.loop.driver import Decision, Driver
from agentlab.core.ports import RunBusy
from agentlab.core.schemas import Approval, Artifact, Event, Iteration, Run, Step
from agentlab.run_service import CreateRun

log = logging.getLogger(__name__)


class MessageBody(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


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

    from agentlab.core.monitor import MonitorUsage, summarize

    @app.get("/monitor/usage", response_model=MonitorUsage)
    def monitor_usage() -> MonitorUsage:
        return summarize(svc.store, svc.cfg.agents)

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
        from agentlab.run_service import create_run_service

        run, driver = await create_run_service(svc, body)
        drivers[run.id] = driver
        spawn(driver, run.id)
        return run

    @app.post("/projects/{project_id}/threads/{thread_id}/messages")
    async def send_message(project_id: str | None, thread_id: str, body: MessageBody) -> dict[str, Any]:
        from agentlab.core.conversation import Message
        from agentlab.core.schemas import EventType
        from agentlab.core.session.service import SessionService
        from agentlab.core.session.store import append_message, get_thread
        from agentlab.run_service import create_run_service

        if not body.text.strip():
            raise HTTPException(422, "message cannot be empty")
        try:
            if project_id:
                svc.projects.get(project_id)
            if len(get_thread(svc.store, thread_id, project_id).messages) >= 998:
                raise HTTPException(409, "conversation is full; start a new conversation")
        except KeyError as exc:
            raise HTTPException(404, "conversation not found in this project") from exc
        try:
            with svc.store.lock_run("turn:" + thread_id):
                turn, turn_id = await SessionService(svc).answer(project_id, thread_id, body.text)
                run = None
                if turn.intent == "task":
                    try:
                        run, driver = await create_run_service(
                            svc,
                            CreateRun(project_id=project_id, thread_id=thread_id, goal=turn.task or body.text),
                            record_user=False,
                        )
                        drivers[run.id] = driver
                        spawn(driver, run.id)
                    except HTTPException as exc:
                        if exc.status_code == 409:
                            turn.reply = (
                                turn.reply[:19800] + "\n\n工作区已有未完成任务。请先完成或中止它,或使用独立 worktree。"
                            )
                        else:
                            turn.reply = turn.reply[:19800] + "\n\n任务未创建,请检查工作区、Gate 和网关配置。"
                message = append_message(
                    svc.store,
                    thread_id,
                    project_id,
                    Message(
                        author="assistant",
                        text=turn.reply,
                        sources=turn.sources,
                        turn_id=turn_id,
                        run_id=run.id if run else None,
                    ),
                )
                svc.bus.publish(
                    Event(
                        run_id="thread:" + thread_id,
                        type=EventType.MESSAGE_CREATED,
                        actor="root",
                        payload={"thread_id": thread_id, "message": message.model_dump(mode="json")},
                    )
                )
                svc.bus.publish(
                    Event(
                        run_id="thread:" + thread_id,
                        type=EventType.TURN_FINISHED,
                        actor="root",
                        payload={"thread_id": thread_id, "turn_id": turn_id},
                    )
                )
                return {"message": message, "turn": turn, "run": run}
        except RunBusy as exc:
            raise HTTPException(409, "conversation is answering another message") from exc

    @app.get("/threads")
    def global_threads() -> list[Any]:
        from agentlab.core.conversation import Conversation

        return [
            Conversation.model_validate(row) for row in svc.store.records("thread") if row.get("project_id") is None
        ]

    @app.post("/threads")
    def create_global_thread(body: dict[str, str]) -> Any:
        from agentlab.core.conversation import Conversation

        thread = Conversation(project_id=None, title=body.get("title", "New conversation"))
        svc.store.put_record("thread", thread.id, thread.model_dump(mode="json"))
        return thread

    @app.post("/threads/{thread_id}/messages")
    async def global_message(thread_id: str, body: MessageBody) -> dict[str, Any]:
        return await send_message(None, thread_id, body)

    @app.get("/threads/{thread_id}/events")
    async def global_events(thread_id: str, request: Request) -> EventSourceResponse:
        return await thread_events(None, thread_id, request)

    @app.get("/projects/{project_id}/threads/{thread_id}/events")
    async def thread_events(project_id: str | None, thread_id: str, request: Request) -> EventSourceResponse:
        from agentlab.core.session.store import get_thread

        try:
            get_thread(svc.store, thread_id, project_id)
        except KeyError as exc:
            raise HTTPException(404, "conversation not found") from exc

        async def stream() -> AsyncIterator[dict[str, str]]:
            subscription = svc.bus.subscribe("thread:" + thread_id)
            try:
                async for event in subscription:
                    if await request.is_disconnected():
                        break
                    yield {"event": str(event.type), "data": event.model_dump_json()}
            finally:
                await subscription.aclose()

        return EventSourceResponse(stream())

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
