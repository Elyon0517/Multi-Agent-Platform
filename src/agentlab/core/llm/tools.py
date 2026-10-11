from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from agentlab.core.ports import GateAdapter, Workspace
from agentlab.core.schemas import FileEdit, GateMode


def tool_spec(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
        },
    }


class WorkerTools:
    def __init__(
        self,
        role: str,
        grants: list[str],
        workspace: Workspace,
        gate: GateAdapter | None,
        memory_search: Callable[[str], Awaitable[dict[str, Any]]],
    ) -> None:
        self.role, self.grants, self.workspace, self.gate = role, grants, workspace, gate
        self.memory_search = memory_search

    @property
    def specs(self) -> list[dict[str, Any]]:
        text = {"type": "string"}
        specs = {
            "workspace_read": tool_spec(
                "workspace_read", "Read source path; empty path lists available context files", {"path": text}
            ),
            "workspace_write": tool_spec(
                "workspace_write", "Replace a workspace file with complete content", {"path": text, "content": text}
            ),
            "gate_run": tool_spec("gate_run", "Run configured objective checks in the sandbox", {}),
            "memory_search": tool_spec("memory_search", "Search readable memories", {"query": text}),
            "workspace_search": tool_spec(
                "workspace_search", "Search source text in the workspace; returns path, line and text", {"query": text}
            ),
        }
        # git_read grants every read-only Git inspection, including other branches and commits.
        git = {
            "git_status": tool_spec("git_status", "Read working tree status", {}),
            "git_branch": tool_spec("git_branch", "List local and remote branches", {}),
            "git_log": tool_spec("git_log", "Read up to 30 commits; empty ref means HEAD", {"ref": text}),
            "git_diff": tool_spec(
                "git_diff",
                "Read diff for path; empty path lists changed files; ref may be empty",
                {"ref": text, "path": text},
            ),
            "git_show": tool_spec(
                "git_show",
                "Read file at ref; empty path lists tree files; empty ref means HEAD",
                {"ref": text, "path": text},
            ),
        }
        if "git_read" in self.grants and hasattr(self.workspace, "inspect_git"):
            specs.update(git)
            granted = {*self.grants, *git}
        else:
            granted = set(self.grants)
        # Writing and gate execution are exclusively granted to Coder.
        return [
            spec
            for name, spec in specs.items()
            if name in granted
            and (name != "gate_run" or self.gate is not None)
            and (self.role == "coder" or name not in {"workspace_write", "gate_run"})
        ]

    async def execute(self, name: str, args: dict[str, Any]) -> Any:
        granted = {s["function"]["name"]: s for s in self.specs}
        if name not in granted:
            raise ValueError("tool not granted")
        props = granted[name]["function"]["parameters"]["properties"]
        if set(args) != set(props) or any(not isinstance(v, str) for v in args.values()):
            raise ValueError("invalid tool arguments")
        if name == "workspace_read":
            if not args["path"]:
                return sorted(await self.workspace.context_files())
            reader = getattr(self.workspace, "read_source", self.workspace.read)
            return {"path": args["path"], "text": reader(args["path"])}
        if name == "workspace_write":
            return {"paths": self.workspace.apply_edits([FileEdit(**args)])}
        if name.startswith("git_"):
            return {"text": await self.workspace.inspect_git(name[4:], **args)}  # type: ignore[attr-defined]
        if name == "workspace_search":
            return await self._search(args["query"][:500])
        if name == "gate_run":
            assert self.gate is not None
            result = await self.gate.run(self.workspace.root, GateMode.FAST)
            return result.model_dump(mode="json")
        return await self.memory_search(args["query"][:4000])

    async def _search(self, query: str) -> list[dict[str, Any]]:
        source_files = getattr(self.workspace, "source_files", None)
        reader = getattr(self.workspace, "read_source", None)
        if not source_files or not reader or not query.strip():
            return []
        matches: list[dict[str, Any]] = []
        for path in await source_files():
            try:
                text = reader(path)
            except (OSError, ValueError, UnicodeError):
                continue
            for line, value in enumerate(text.splitlines(), 1):
                if query.casefold() in value.casefold():
                    matches.append({"path": path, "line": line, "text": value[:300]})
                    if len(matches) >= 60:
                        return matches
        return matches
