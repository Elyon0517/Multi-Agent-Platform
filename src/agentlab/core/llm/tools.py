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
        gate: GateAdapter,
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
        }
        # Writing and gate execution are exclusively granted to Coder.
        return [
            spec
            for name, spec in specs.items()
            if name in self.grants and (self.role == "coder" or name not in {"workspace_write", "gate_run"})
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
        if name == "gate_run":
            result = await self.gate.run(self.workspace.root, GateMode.FAST)
            return result.model_dump(mode="json")
        return await self.memory_search(args["query"][:4000])
