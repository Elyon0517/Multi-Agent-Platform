"""Durable external-write approvals; unknown remote outcomes are never replayed."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel

from agentlab.adapters.mcp import describe
from agentlab.bootstrap import Services
from agentlab.core.conversation import Message
from agentlab.core.ports import RunBusy
from agentlab.core.schemas import Event, EventType, utcnow
from agentlab.core.session.store import append_message, get_thread

ToolDecision = Literal["allow", "deny", "confirm_done", "close_unknown"]
ToolStatus = Literal[
    "pending", "executing", "done", "failed", "denied", "unknown_outcome", "confirmed_done", "closed_unknown",
]


class ToolApprovalView(BaseModel):
    id: str
    tool: str
    status: ToolStatus


def approval_views(svc: Services, project_id: str | None, thread_id: str) -> list[ToolApprovalView]:
    get_thread(svc.store, thread_id, project_id)
    return [ToolApprovalView.model_validate(row) for row in svc.store.records("mcp_approval")
            if row.get("project_id") == project_id and row["thread_id"] == thread_id]


def _record(svc: Services, approval_id: str) -> dict[str, Any]:
    row = next((r for r in svc.store.records("mcp_approval") if r["id"] == approval_id), None)
    if row is None:
        raise HTTPException(404, "approval not found in this conversation")
    return row


def _finish(svc: Services, record: dict[str, Any], status: ToolStatus, text: str) -> None:
    message = None
    with svc.store.transaction():
        record.update(status=status, finished_at=utcnow().isoformat(), result_text=text)
        svc.store.put_record("mcp_approval", record["id"], record)
        thread = get_thread(svc.store, record["thread_id"], record.get("project_id"))
        if len(thread.messages) < 1000:
            message = append_message(svc.store, record["thread_id"], record.get("project_id"), Message(
                author="system", kind="tool_result", text=text,
                payload={"approval_id": record["id"], "status": status},
            ))
    if message:
        svc.bus.publish(Event(run_id="thread:" + record["thread_id"], type=EventType.MESSAGE_CREATED, actor="root",
                              payload={"message": message.model_dump(mode="json")}))


def _unknown(svc: Services, record: dict[str, Any]) -> None:
    _finish(svc, record, "unknown_outcome", (
        f"`{record['tool']}` was interrupted. Its external result is unknown; it will not be run again. "
        "Check the external service, then confirm it completed or close this approval without retrying."
    ))


def recover_tool_approvals(svc: Services) -> None:
    """Only recover calls whose lifecycle and execution locks are no longer held."""
    for row in svc.store.records("mcp_approval"):
        if row.get("status") != "executing":
            continue
        try:
            with svc.store.lock_run("turn:" + row["thread_id"]), svc.store.lock_run("tool-approval:" + row["id"]):
                current = _record(svc, row["id"])
                if current["status"] != "executing":
                    continue
                try:
                    get_thread(svc.store, current["thread_id"], current.get("project_id"))
                except KeyError:
                    # Old versions could delete the thread during a call. Retain the uncertain audit record.
                    current["status"] = "unknown_outcome"
                    svc.store.put_record("mcp_approval", current["id"], current)
                else:
                    _unknown(svc, current)
        except (RunBusy, HTTPException):
            continue


async def decide_tool_approval(
    svc: Services, project_id: str | None, thread_id: str, approval_id: str, decision: ToolDecision,
) -> dict[str, str]:
    try:
        # The same turn lock protects messages, tool calls, thread deletion and project deletion.
        with svc.store.lock_run("turn:" + thread_id), svc.store.lock_run("tool-approval:" + approval_id):
            try:
                get_thread(svc.store, thread_id, project_id)
            except KeyError as exc:
                raise HTTPException(404, "conversation not found in this project") from exc
            record = _record(svc, approval_id)
            if record["thread_id"] != thread_id or record.get("project_id") != project_id:
                raise HTTPException(404, "approval not found in this conversation")
            if record["status"] == "executing":
                # A stale call cannot still be running: we own both of its execution locks.
                _unknown(svc, record)
            if decision in {"confirm_done", "close_unknown"}:
                if record["status"] != "unknown_outcome":
                    raise HTTPException(409, "only an unknown outcome can be reconciled")
                status: ToolStatus = "confirmed_done" if decision == "confirm_done" else "closed_unknown"
                text = (f"Confirmed `{record['tool']}` completed in the external service."
                        if decision == "confirm_done" else f"Closed `{record['tool']}` with an unknown outcome.")
                _finish(svc, record, status, text + " The tool was not called again.")
            elif record["status"] != "pending":
                raise HTTPException(409, f"already {record['status']}; the tool will not be called again")
            elif decision == "deny":
                _finish(svc, record, "denied", f"Rejected `{record['tool']}`; it was not run.")
            else:
                tool = next((t for t in await svc.mcp.tools("root") if t.qualified == record["tool"]), None)
                if tool is None:
                    raise HTTPException(503, "the tool's MCP server is not available")
                # This commit must finish before the remote call. Never hold a DB transaction over the network.
                record.update(status="executing", started_at=utcnow().isoformat())
                svc.store.put_record("mcp_approval", approval_id, record)
                try:
                    result = await svc.mcp.call(tool, record["args"])
                except Exception:
                    _unknown(svc, record)
                    return {"status": record["status"]}
                except BaseException:
                    _unknown(svc, record)
                    raise
                status = "failed" if result.get("error") else "done"
                _finish(svc, record, status, f"Ran `{tool.qualified}`:\n```\n{describe(result)[:4000]}\n```")
            return {"status": record["status"]}
    except RunBusy as exc:
        raise HTTPException(409, "conversation or tool approval is busy") from exc
