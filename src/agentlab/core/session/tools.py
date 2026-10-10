from __future__ import annotations

from typing import Any

from agentlab.adapters.workspace import GitWorkspace
from agentlab.core.llm.tools import tool_spec
from agentlab.core.ports import Store
from agentlab.services import KnowledgeService


class SessionTools:
    def __init__(
        self,
        workspace: GitWorkspace | None,
        knowledge: KnowledgeService,
        store: Store,
        project_id: str | None,
        thread_id: str,
    ) -> None:
        self.workspace, self.knowledge, self.store = workspace, knowledge, store
        self.project_id, self.thread_id = project_id, thread_id

    @property
    def specs(self) -> list[dict[str, Any]]:
        text = {"type": "string"}
        specs = [
            tool_spec("memory_search", "Search uploaded documents and readable memories", {"query": text}),
            tool_spec(
                "artifact_read", "Read one diff, gate report or review from this conversation", {"artifact_id": text}
            ),
            tool_spec("run_status", "Summarize this conversation's run status, gate and reviews", {}),
        ]
        if self.workspace:
            specs += [
                tool_spec("file_list", "List project source files", {}),
                tool_spec("file_read", "Read a project source file", {"path": text}),
                tool_spec("file_search", "Search project source text", {"query": text}),
                tool_spec("git_status", "Read working tree status", {}),
                tool_spec("git_branch", "List local and remote branches", {}),
                tool_spec("git_log", "Read up to 30 commits; empty ref means HEAD", {"ref": text}),
                tool_spec(
                    "git_diff",
                    "Read diff for path; empty path lists changed files; ref may be empty",
                    {"ref": text, "path": text},
                ),
                tool_spec(
                    "git_show",
                    "Read file at ref; empty path lists tree files; empty ref means HEAD",
                    {"ref": text, "path": text},
                ),
            ]
        return specs

    async def execute(self, name: str, args: dict[str, Any]) -> Any:
        specs = {s["function"]["name"]: s for s in self.specs}
        if name not in specs:
            raise ValueError("tool not granted")
        properties = specs[name]["function"]["parameters"]["properties"]
        if set(args) != set(properties) or any(not isinstance(v, str) for v in args.values()):
            raise ValueError("invalid tool arguments")
        if name == "memory_search":
            hits = await self.knowledge.search(self.project_id, "root", args["query"][:4000])
            return [{"ref": h.item.id, "text": h.item.text, "source": h.item.source} for h in hits]
        if name == "artifact_read":
            for run in self.store.list_runs():
                if run.project_id == self.project_id and run.thread_id == self.thread_id:
                    for artifact in self.store.artifacts(run.id):
                        if artifact.id == args["artifact_id"]:
                            return {"content_ref": artifact.content_ref, "kind": artifact.kind}
            raise KeyError("artifact not found in this conversation")
        if name == "run_status":
            runs = [
                r for r in self.store.list_runs() if r.project_id == self.project_id and r.thread_id == self.thread_id
            ]
            return [
                {
                    "run": r.model_dump(mode="json"),
                    "artifacts": [{"id": a.id, "kind": a.kind} for a in self.store.artifacts(r.id)[-8:]],
                    "events": [
                        {"type": e.type, "actor": e.actor, "payload": e.payload}
                        for e in self.store.events(r.id)
                        if e.type in {"gate.finished", "arbiter.decision"}
                    ][-2:],
                }
                for r in runs[-5:]
            ]
        assert self.workspace is not None
        if name.startswith("git_"):
            return {"text": await self.workspace.inspect_git(name[4:], **args)}
        if name == "file_read":
            return {"path": args["path"], "text": self.workspace.read_source(args["path"])}
        files = await self.workspace.source_files()
        if name == "file_list":
            return sorted(files)
        matches = []
        for path in files:
            try:
                text = self.workspace.read_source(path)
            except (OSError, ValueError, UnicodeError):
                continue
            for line, value in enumerate(text.splitlines(), 1):
                if args["query"].casefold() in value.casefold():
                    matches.append({"path": path, "line": line, "text": value[:500]})
                    if len(matches) >= 60:
                        return matches
        return matches
