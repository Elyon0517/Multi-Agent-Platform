"""External tools over MCP (Model Context Protocol), e.g. GitHub and web page fetching.

Servers are declared in `config/mcp.yaml`, started on first use and kept alive for the process. Tools a
server marks read-only (`readOnlyHint`), or that the config lists as read-only, run without asking; any
other tool changes outside state and needs the user's approval before it runs.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)
# Servers sometimes print non-protocol lines (e.g. installer output) on stdout; the SDK skips them but logs a
# full traceback for each, which would flood the server log.
logging.getLogger("mcp.client.stdio").setLevel(logging.CRITICAL)

START_TIMEOUT_S = 90  # first start may pull a Docker image or download a package
CALL_TIMEOUT_S = 120
# Secrets that can come from an existing CLI login when not set in .env.
FALLBACK_COMMANDS = {"GITHUB_PERSONAL_ACCESS_TOKEN": ["gh", "auth", "token"]}
_VAR = re.compile(r"\$\{([A-Z0-9_]+)\}")


class McpServerCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    roles: list[str]
    read_only_tools: list[str] = Field(default_factory=list)


class McpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    servers: dict[str, McpServerCfg] = Field(default_factory=dict)


def load_mcp_config(config_dir: Path) -> McpConfig:
    path = config_dir / "mcp.yaml"
    return McpConfig.model_validate(yaml.safe_load(path.read_text()) or {}) if path.exists() else McpConfig()


@dataclass(frozen=True)
class McpTool:
    server: str
    name: str
    description: str
    schema: dict[str, Any]
    read_only: bool

    @property
    def qualified(self) -> str:
        # Function names must match ^[a-zA-Z0-9_-]{1,64}$ for the model APIs.
        return re.sub(r"[^a-zA-Z0-9_-]", "_", f"{self.server}__{self.name}")[:64]

    @property
    def spec(self) -> dict[str, Any]:
        schema = self.schema or {"type": "object", "properties": {}}
        access = "read-only" if self.read_only else "changes external state; runs only after the user approves"
        return {"type": "function", "function": {
            "name": self.qualified, "description": f"[{self.server}, {access}] {self.description}"[:1024],
            "parameters": schema,
        }}


class McpHub:
    def __init__(self, cfg: McpConfig, env: Callable[[], dict[str, str]]) -> None:
        self.cfg, self._env = cfg, env
        self._sessions: dict[str, Any] = {}
        self._tools: dict[str, list[McpTool]] = {}
        self.errors: dict[str, str] = {}
        self._starting: dict[str, asyncio.Task[None]] = {}
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    def _resolve_env(self, values: dict[str, str]) -> dict[str, str]:
        source = {**os.environ, **self._env()}

        def lookup(name: str) -> str:
            if source.get(name):
                return source[name]
            command = FALLBACK_COMMANDS.get(name)
            if command:
                result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
                if result.returncode == 0:
                    return result.stdout.strip()
            return ""

        return {key: _VAR.sub(lambda m: lookup(m.group(1)), value) for key, value in values.items()}

    async def _serve(self, name: str, cfg: McpServerCfg, ready: asyncio.Future[None]) -> None:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, get_default_environment, stdio_client
        from mcp.types import PaginatedRequestParams

        params = StdioServerParameters(
            command=cfg.command, args=cfg.args, env={**get_default_environment(), **self._resolve_env(cfg.env)}
        )
        try:
            with open(os.devnull, "w") as quiet:
                async with stdio_client(params, errlog=quiet) as (read, write), ClientSession(read, write) as session:
                    await session.initialize()
                    tools: list[Any] = []
                    cursor: str | None = None
                    while True:
                        request: PaginatedRequestParams | None = (
                            PaginatedRequestParams(cursor=cursor) if cursor else None
                        )
                        page = await session.list_tools(params=request)
                        tools.extend(page.tools)
                        cursor = page.next_cursor
                        if not cursor:
                            break
                    self._tools[name] = [
                        McpTool(name, t.name, t.description or "", dict(t.input_schema or {}),
                                bool(t.annotations and t.annotations.read_only_hint) or t.name in cfg.read_only_tools)
                        for t in tools
                    ]
                    self._sessions[name] = session
                    self.errors.pop(name, None)
                    ready.set_result(None)
                    await self._stop.wait()
        except BaseException as exc:
            self.errors[name] = type(exc).__name__
            if not ready.done():
                ready.set_exception(exc)
            if not isinstance(exc, Exception):
                raise
        finally:
            self._sessions.pop(name, None)

    async def _ensure(self, name: str) -> None:
        if name in self._sessions:
            return
        task = self._starting.get(name)
        if task is None or task.done():
            ready: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            server = asyncio.create_task(self._serve(name, self.cfg.servers[name], ready))
            self._tasks.append(server)

            async def wait() -> None:
                await ready

            task = self._starting[name] = asyncio.create_task(wait())
        await asyncio.wait_for(asyncio.shield(task), START_TIMEOUT_S)

    async def tools(self, role: str) -> list[McpTool]:
        """Tools available to a role; servers that fail to start are skipped and reported in status()."""
        found: list[McpTool] = []
        for name, server in self.cfg.servers.items():
            if role not in server.roles:
                continue
            try:
                await self._ensure(name)
            except Exception as exc:  # an unavailable server must not stop Root or a run
                self.errors[name] = self.errors.get(name) or type(exc).__name__
                log.warning("MCP server %s unavailable: %s", name, type(exc).__name__)
                continue
            found.extend(self._tools.get(name, []))
        return found

    async def call(self, tool: McpTool, args: dict[str, Any]) -> Any:
        await self._ensure(tool.server)
        result = await asyncio.wait_for(self._sessions[tool.server].call_tool(tool.name, args), CALL_TIMEOUT_S)
        content = [c.model_dump(mode="json", exclude_none=True) for c in getattr(result, "content", []) or []]
        texts = [c.get("text", "") for c in content if c.get("type") == "text"]
        payload: dict[str, Any] = {"text": "\n".join(texts)} if texts else {"content": content}
        structured = getattr(result, "structured_content", None)
        if structured and not texts:
            payload["structured"] = structured
        if getattr(result, "is_error", False):
            payload["error"] = True
        return payload

    def status(self) -> list[dict[str, Any]]:
        return [
            {"name": name, "roles": server.roles, "running": name in self._sessions,
             "tools": len(self._tools.get(name, [])), "error": self.errors.get(name)}
            for name, server in self.cfg.servers.items()
        ]

    async def close(self) -> None:
        self._stop.set()
        for task in self._tasks:
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(task, 10)


def describe(args: dict[str, Any]) -> str:
    return json.dumps(args, ensure_ascii=False)[:2000]
