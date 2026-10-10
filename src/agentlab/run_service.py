from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel

from agentlab.bootstrap import MissingGatewayConfig, Services
from agentlab.core.loop.driver import Driver
from agentlab.core.ports import RunBusy, execution_error_reason
from agentlab.core.schemas import Run
from agentlab.demo import seed_demo_workspace


class CreateRun(BaseModel):
    goal: str
    thread_id: str | None = None
    workspace: str | None = None
    runtime: str | None = None
    language: str | None = None
    project_id: str | None = None
    step_id: str | None = None


async def create_run_service(svc: Services, body: CreateRun, *, record_user: bool = True) -> tuple[Run, Driver]:
    from contextlib import nullcontext

    try:
        with svc.store.lock_run("project:" + body.project_id) if body.project_id else nullcontext():
            return await _create_run_service(svc, body, record_user=record_user)
    except RunBusy as exc:
        raise HTTPException(409, str(exc)) from exc


async def _create_run_service(svc: Services, body: CreateRun, *, record_user: bool = True) -> tuple[Run, Driver]:
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
        from agentlab.core.session.store import get_thread

        try:
            conversation = get_thread(svc.store, body.thread_id, body.project_id)
        except KeyError:
            conversation = None
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
        Path(body.workspace) if body.workspace else seed_demo_workspace(Path(tempfile.mkdtemp(prefix="agentlab-demo-")))
    )
    try:
        driver = svc.driver(ws, body.runtime, body.language, body.project_id)
        if conversation:
            driver.recovery_options["conversation"] = [m.model_dump(mode="json") for m in conversation.messages[-20:]]
    except MissingGatewayConfig as e:
        raise HTTPException(400, f"{type(e).__name__}: {e}") from e

    def record_conversation(run: Run) -> None:
        if not conversation:
            return
        from agentlab.core.conversation import Message
        from agentlab.core.schemas import Event, EventType
        from agentlab.core.session.store import append_message

        if new_conversation:
            svc.store.put_record("thread", conversation.id, conversation.model_dump(mode="json"))
        if record_user:
            message = append_message(
                svc.store, conversation.id, body.project_id, Message(author="user", text=body.goal, run_id=run.id)
            )
            svc.bus.publish(
                Event(
                    run_id="thread:" + conversation.id,
                    type=EventType.MESSAGE_CREATED,
                    actor="user",
                    payload={"message": message.model_dump(mode="json")},
                )
            )

    try:
        await driver.workspace.ensure_repo()  # type: ignore[attr-defined]
        run = await driver.create_async(
            body.goal, project_id=body.project_id or "default", thread_id=body.thread_id, on_create=record_conversation
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
            svc.projects.link_run(body.project_id, body.step_id, run.id, locked=True)
        except (KeyError, StopIteration) as e:
            raise HTTPException(404, "project or step not found") from e
    return run, driver
