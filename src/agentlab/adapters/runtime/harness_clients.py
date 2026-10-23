"""Thin SDK bindings; AgentLab never implements the SDKs' inner agent loop."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any, cast

from agentlab.core.schemas import Usage


@dataclass
class HarnessReply:
    text: str = ""
    structured: dict[str, Any] | None = None
    usage: Usage = field(default_factory=Usage)
    metered: bool = False
    model: str = "sdk-default"


class HarnessFailure(RuntimeError):
    kind = "harness_failed"

    def __init__(self, message: str, reply: HarnessReply) -> None:
        super().__init__(message)
        self.reply = reply


class CodexClient:
    async def run(self, *, source: Path, state: Path, prompt: str, model: str | None,
                  update: Callable[[dict[str, Any]], None]) -> HarnessReply:
        from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, Sandbox

        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Do not inherit user/project MCP, hooks, skills or writable roots. Copy authentication only.
        auth = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json"
        if auth.is_file() and not (state / "auth.json").exists():
            shutil.copyfile(auth, state / "auth.json")
            (state / "auth.json").chmod(0o600)
        home = state / "home"
        home.mkdir(exist_ok=True, mode=0o700)
        config = CodexConfig(env={"CODEX_HOME": str(state), "HOME": str(home)}, cwd=str(source))
        async with AsyncCodex(config) as codex:
            thread = await codex.thread_start(
                cwd=str(source), model=model, sandbox=Sandbox.workspace_write, approval_mode=ApprovalMode.deny_all,
                config={"sandbox_workspace_write": {"network_access": False, "exclude_tmpdir_env_var": True,
                                                     "exclude_slash_tmp": True},
                        "agents": {"enabled": False}, "allow_login_shell": False},
            )
            update({"session_id": thread.id})
            turn = await thread.turn(prompt)
            update({"turn_id": turn.id})
            try:
                result = await turn.run()
            except asyncio.CancelledError:
                # Close the server before returning control to Driver; never export a live writer.
                await asyncio.shield(turn.interrupt())
                raise
            usage = Usage()
            if result.usage is not None:
                usage.tokens_in = result.usage.total.input_tokens
                usage.tokens_out = result.usage.total.output_tokens
            update({"sdk_result": {"status": result.status.value, "text": result.final_response,
                                   "usage": usage.model_dump()}})
            reply = HarnessReply(text=result.final_response or "", usage=usage,
                                 metered=result.usage is not None, model=model or "codex-default")
            if result.status.value != "completed":
                raise HarnessFailure("codex_turn_not_completed", reply)
            return reply


async def review_tool_policy(data: dict[str, Any], _tool_id: str | None, _context: Any,
                             *, source: Path) -> dict[str, Any]:
    name = data.get("tool_name", "")
    args = data.get("tool_input", {})
    path = args.get("file_path") if name == "Read" else args.get("path") or "."
    safe_path = (isinstance(path, str) and not path.startswith("~")
                 and (source / path).resolve().is_relative_to(source.resolve()))
    pattern = args.get("pattern", "")
    safe_pattern = name != "Glob" or (isinstance(pattern, str) and ".." not in pattern
                                      and not Path(pattern).is_absolute() and not pattern.startswith("~"))
    if name not in {"Read", "Glob", "Grep", "StructuredOutput"} or (
        name != "StructuredOutput" and (not safe_path or not safe_pattern)
    ):
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": "Reviewer is read-only"}}
    return {}


class ClaudeClient:
    async def run(self, *, source: Path, state: Path, prompt: str, model: str | None,
                  schema: dict[str, Any], update: Callable[[dict[str, Any]], None]) -> HarnessReply:
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, HookMatcher, ResultMessage, SystemMessage

        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        home = state / "home"
        home.mkdir(exist_ok=True, mode=0o700)
        options = ClaudeAgentOptions(
            cwd=str(source), model=model, tools=["Read", "Glob", "Grep"],
            allowed_tools=["Read", "Glob", "Grep", "StructuredOutput"],
            disallowed_tools=["Bash", "Write", "Edit", "NotebookEdit", "Agent", "Task", "Skill"],
            permission_mode="dontAsk", setting_sources=[], strict_mcp_config=True, mcp_servers={}, skills=[],
            env={"CLAUDE_CONFIG_DIR": str(state), "HOME": str(home)},
            hooks={"PreToolUse": [HookMatcher(hooks=[cast(Any, partial(review_tool_policy, source=source))])]},
            output_format={"type": "json_schema", "schema": schema},
        )
        result = None
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)
            try:
                async for message in client.receive_response():
                    if isinstance(message, SystemMessage) and message.subtype == "init":
                        update({"session_id": message.data.get("session_id")})
                    if isinstance(message, ResultMessage):
                        result = message
                        update({"session_id": message.session_id,
                                "sdk_result": {"subtype": message.subtype, "is_error": message.is_error,
                                               "structured_output": message.structured_output,
                                               "usage": message.usage,
                                               "total_cost_usd": message.total_cost_usd}})
            except asyncio.CancelledError:
                await asyncio.shield(client.interrupt())
                raise
        if result is None:
            raise RuntimeError("claude_review_not_completed")
        raw = result.usage or {}
        usage = Usage(tokens_in=int(raw.get("input_tokens", 0)) + int(raw.get("cache_read_input_tokens", 0))
                      + int(raw.get("cache_creation_input_tokens", 0)),
                      tokens_out=int(raw.get("output_tokens", 0)), cost_cents=(result.total_cost_usd or 0) * 100)
        # Each invocation starts a fresh session, so this terminal cost is not cumulative across retries.
        reply = HarnessReply(structured=json.loads(json.dumps(result.structured_output)), usage=usage,
                             metered=result.usage is not None, model=model or "claude-default")
        if result.is_error or result.subtype != "success" or result.structured_output is None:
            raise HarnessFailure("claude_review_not_completed", reply)
        return reply
