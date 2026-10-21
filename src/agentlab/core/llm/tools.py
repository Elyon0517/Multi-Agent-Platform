from __future__ import annotations

import hashlib
import json
import re
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
        read_state: dict[str, Any] | None = None,
        evidence_state: dict[str, Any] | None = None,
    ) -> None:
        self.role, self.grants, self.workspace, self.gate = role, grants, workspace, gate
        self.memory_search = memory_search
        self.read_state = read_state if read_state is not None else {}
        self.read_state.setdefault("pending", [])
        self.evidence_state = evidence_state

    @property
    def specs(self) -> list[dict[str, Any]]:
        text = {"type": "string"}
        specs = {
            "workspace_read": tool_spec(
                "workspace_read",
                "Read source path; empty path lists files. "
                "Optional 1-based line_start/line_end read large files in chunks; follow continuation markers. "
                "char_start is a zero-based character offset within line_start for long single lines. "
                "Dependency directories such as node_modules are excluded; use project source or API documentation.",
                {"path": text, "line_start": {"type": "integer", "minimum": 1},
                 "line_end": {"type": "integer", "minimum": 1},
                 "char_start": {"type": "integer", "minimum": 0}}
            ),
            "workspace_write": tool_spec(
                "workspace_write", "Replace a workspace file with complete content", {"path": text, "content": text}
            ),
            "gate_run": tool_spec("gate_run", "Run configured objective checks in the sandbox", {}),
            "memory_search": tool_spec("memory_search", "Search readable memories", {"query": text}),
            "workspace_search": tool_spec(
                "workspace_search", "Search one literal substring (not AND/OR keywords). "
                "Search separate amounts separately. "
                "Optional exact path restricts results to that evidence file; zero matches do not prove absence.",
                {"query": text, "path": text},
            ),
        }
        specs["workspace_read"]["function"]["parameters"]["required"] = ["path"]
        specs["workspace_search"]["function"]["parameters"]["required"] = ["query"]
        specs["workspace_read_next"] = tool_spec(
            "workspace_read_next", "Read the next pending truncated range, using the exact saved cursor.", {},
        )
        specs["workspace_read_status"] = tool_spec(
            "workspace_read_status",
            "List pending truncated reads. Empty means requested ranges were delivered, not verified.", {},
        )
        specs["workspace_excerpt"] = tool_spec(
            "workspace_excerpt",
            "Read a bounded excerpt from one source line, for targeted evidence (including minified HTML). "
            "Use workspace_search line/char_start, then request up to 2000 characters. "
            "This completes only the requested excerpt and never queues the rest of the file.",
            {"path": text, "line_start": {"type": "integer", "minimum": 1},
             "char_start": {"type": "integer", "minimum": 0},
             "char_count": {"type": "integer", "minimum": 1, "maximum": 2000}},
        )
        if self.evidence_state is not None and "workspace_read" in self.grants and self.role == "coder":
            specs["evidence_status"] = tool_spec(
                "evidence_status", "Next required evidence items; coverage is not semantic approval.", {})
            specs["evidence_get"] = tool_spec(
                "evidence_get", "Read a saved evidence verdict, calculation and citation locations by ID. "
                "Quotes are abbreviated here; the full validated record remains in the final evidence artifact.",
                {"id": text})
            specs["evidence_capture"] = tool_spec(
                "evidence_capture", "Capture an exact citation from a known file range. Returns citation_id. "
                "Use {citation_id: ID} as claim or source in evidence_record instead of retyping quotes. "
                "Offsets are zero-based within the first line; capture only the claim/evidence needed. "
                "Each capture is limited to 2000 characters and 31 lines; split larger ranges into separate citations.",
                {"path": text, "line_start": {"type": "integer", "minimum": 1},
                 "line_end": {"type": "integer", "minimum": 1},
                 "char_start": {"type": "integer", "minimum": 0},
                 "char_count": {"type": "integer", "minimum": 8, "maximum": 2000}})
            specs["evidence_record"] = tool_spec(
                "evidence_record", "Save one evidence item. Pass JSON string with "
                "id, claim {path,line_start,line_end,quote}, "
                "sources [{path,line_start,line_end,quote}], verdict, reason, calculation (empty if inapplicable), "
                "claim and each source may instead be {citation_id: ID} from evidence_capture. "
                "Do not record unfinished research as a partial verdict; finish checking all subclaims first. "
                "negative_claim boolean, searches [{path,query}] (empty if inapplicable). Quotes must match exactly. "
                "Negative claims must reference scoped searches actually executed in this revision.", {"record": text})
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
        if "workspace_read" in granted:
            granted.update({"workspace_read_next", "workspace_read_status", "workspace_excerpt"})
        if self.evidence_state is not None and "workspace_read" in granted and self.role == "coder":
            granted.update({"evidence_status", "evidence_record", "evidence_capture", "evidence_get"})
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
        if name == "evidence_capture":
            if set(args) != set(props) or not isinstance(args["path"], str):
                raise ValueError("invalid capture arguments")
            for key, minimum in (("line_start", 1), ("line_end", 1), ("char_start", 0), ("char_count", 8)):
                if type(args[key]) is not int or args[key] < minimum:
                    raise ValueError("invalid capture range")
            if args["char_count"] > 2000 or not 0 <= args["line_end"] - args["line_start"] <= 30:
                return {
                    "error": "invalid_capture_range",
                    "message": (
                        "Capture at most 2000 characters and 31 lines. "
                        "Split larger ranges into separate citations; no citation was saved."
                    ),
                    "limits": {"max_char_count": 2000, "max_lines": 31},
                }
        elif name == "workspace_excerpt":
            if set(args) != set(props) or not isinstance(args["path"], str):
                raise ValueError("invalid excerpt arguments")
            for key, minimum in (("line_start", 1), ("char_start", 0), ("char_count", 1)):
                if type(args[key]) is not int or args[key] < minimum:
                    raise ValueError("invalid excerpt range")
            if args["char_count"] > 2000:
                raise ValueError("excerpt too large")
        elif name == "workspace_read":
            if "path" not in args or set(args) - set(props) or not isinstance(args["path"], str):
                raise ValueError("invalid tool arguments")
            for key in ("line_start", "line_end"):
                if key in args and (type(args[key]) is not int or args[key] < 1):
                    raise ValueError("invalid line range")
            if "char_start" in args and (type(args["char_start"]) is not int or args["char_start"] < 0):
                raise ValueError("invalid character offset")
            if args.get("line_end", args.get("line_start", 1)) < args.get("line_start", 1):
                raise ValueError("invalid line range")
        elif name == "workspace_search":
            if "query" not in args or set(args) - set(props) or any(not isinstance(v, str) for v in args.values()):
                raise ValueError("invalid search arguments")
        elif set(args) != set(props) or any(not isinstance(v, str) for v in args.values()):
            raise ValueError("invalid tool arguments")
        if name == "workspace_excerpt":
            reader = getattr(self.workspace, "source_text", None)
            if reader is None:
                raise ValueError("source excerpts unavailable")
            lines = reader(args["path"]).splitlines(keepends=True)
            index, start = args["line_start"] - 1, args["char_start"]
            if index >= len(lines) or start > len(lines[index]):
                raise ValueError("excerpt outside source")
            value = lines[index][start:start + args["char_count"]]
            return {"path": args["path"], "line": index + 1, "char_start": start,
                    "char_end": start + len(value), "text": value, "scope": "requested excerpt only"}
        if name == "evidence_get":
            assert self.evidence_state is not None
            row = self.evidence_state.get("records", {}).get(args["id"])
            if row is None:
                return {"error": "record_not_found"}
            def abbreviated(c: dict[str, Any]) -> dict[str, Any]:
                return {**c, "quote": c["quote"][:200], "quote_abbreviated": len(c["quote"]) > 200}
            return {**row, "reason": row["reason"][:600], "calculation": row["calculation"][:1000],
                    "claim": abbreviated(row["claim"]), "sources": [abbreviated(c) for c in row["sources"]]}
        if name == "evidence_capture":
            assert self.evidence_state is not None
            contract = self.evidence_state["contract"]
            allowed = set(contract["source_paths"]) | {r["claim_path"] for r in contract["requirements"]}
            if args["path"] not in allowed:
                raise ValueError("capture path outside evidence contract")
            lines = self.workspace.source_text(args["path"]).splitlines(keepends=True)
            start, end, offset = args["line_start"], args["line_end"], args["char_start"]
            if end > len(lines) or offset >= len(lines[start - 1]):
                raise ValueError("capture outside source")
            quote = "".join(lines[start - 1:end])[offset:offset + args["char_count"]]
            if len(quote) < 8:
                raise ValueError("capture must contain at least eight characters")
            citation = {"path": args["path"], "line_start": start,
                        "line_end": start + len(quote.splitlines()) - 1, "quote": quote}
            citation_id = hashlib.sha256(json.dumps(citation, sort_keys=True).encode()).hexdigest()[:20]
            self.evidence_state.setdefault("citations", {})[citation_id] = citation
            return {"citation_id": citation_id, **citation}
        if name in {"evidence_status", "evidence_record"}:
            from agentlab.core.evidence import EvidenceContract, EvidenceRecord, evidence_status, validate_record
            assert self.evidence_state is not None
            if name == "evidence_record":
                try:
                    data = json.loads(args["record"])
                    if not isinstance(data, dict):
                        raise ValueError("record must be an object")
                    def resolve(citation: Any) -> Any:
                        assert self.evidence_state is not None
                        if isinstance(citation, dict) and set(citation) == {"citation_id"}:
                            found = self.evidence_state.get("citations", {}).get(citation["citation_id"])
                            if found is None:
                                raise ValueError("unknown citation_id; use evidence_capture first")
                            return found
                        return citation
                    data["claim"] = resolve(data.get("claim"))
                    if isinstance(data.get("sources"), list):
                        data["sources"] = [resolve(c) for c in data["sources"]]
                    record = EvidenceRecord.model_validate(data)
                    validate_record(record, EvidenceContract.model_validate(self.evidence_state["contract"]),
                                    self.workspace.source_text, self.evidence_state.get("searches", []))
                except ValueError as exc:
                    return {"error": "invalid_evidence", "detail": str(exc)[:2000]}
                self.evidence_state.setdefault("records", {})[record.id] = record.model_dump()
                status = evidence_status(self.evidence_state)
                status["next_requirements"] = status["next_requirements"][:1]
                return status
            return evidence_status(self.evidence_state)
        if name == "workspace_read_status":
            return {"pending": self.read_state["pending"], "meaning": "Delivery only; not evidence verification."}
        if name == "workspace_read_next":
            if not self.read_state["pending"]:
                return {"pending": [], "text": "No truncated requested ranges remain."}
            return self._read_page(dict(self.read_state["pending"][0]), enqueue=False)
        if name == "workspace_read":
            if not args["path"]:
                if hasattr(self.workspace, "source_files"):
                    return sorted(await self.workspace.source_files())
                return sorted(await self.workspace.context_files())
            return self._read_page(args)
        if name == "workspace_write":
            return {"paths": self.workspace.apply_edits([FileEdit(**args)])}
        if name.startswith("git_"):
            return {"text": await self.workspace.inspect_git(name[4:], **args)}  # type: ignore[attr-defined]
        if name == "workspace_search":
            query, path = args["query"][:500], args.get("path", "")
            result = await self._search(query, path)
            if self.evidence_state is not None and path and query.strip():
                self.evidence_state.setdefault("searches", []).append({"path": path, "query": query})
            return result
        if name == "gate_run":
            assert self.gate is not None
            gate_result = await self.gate.run(self.workspace.root, GateMode.FAST)
            return gate_result.model_dump(mode="json")
        return await self.memory_search(args["query"][:4000])

    def _read_page(self, args: dict[str, Any], *, enqueue: bool = True) -> dict[str, Any]:
        pending = self.read_state["pending"]
        request = {"path": args["path"], "line_start": args.get("line_start", 1),
                   "char_start": args.get("char_start", 0),
                   "line_end": args.get("line_end", args.get("line_start", 1) + 199)}
        # Finish a truncated range before jumping ahead in the same file. Keep the new request queued.
        existing = next((item for item in pending if item["path"] == request["path"]), None)
        actual = dict(existing or request)
        reader = getattr(self.workspace, "read_source", self.workspace.read)
        text = reader(actual["path"], **{k: v for k, v in actual.items() if k != "path"})
        # Do not mutate the cursor until a read succeeds.
        if enqueue and request != actual and request not in pending:
            pending.append(request)
        if existing is not None:
            pending.remove(existing)
        marker = re.search(r"\n\[more text; continue with line_start=(\d+); char_start=(\d+);", text)
        if marker:
            cursor = {**actual, "line_start": int(marker[1]), "char_start": int(marker[2])}
            pending.insert(0, cursor)
        return {"path": actual["path"], "text": text, "actual_range": actual,
                "request_deferred": request != actual, "pending": [dict(item) for item in pending[:8]],
                "pending_count": len(pending),
                "next_action": "Call workspace_read_next until pending is empty; then verify each claim."
                if pending else "Requested ranges delivered; this does not mean claims are verified."}

    async def _search(self, query: str, path: str = "") -> list[dict[str, Any]]:
        source_files = getattr(self.workspace, "source_files", None)
        reader = getattr(self.workspace, "source_text", None) or getattr(self.workspace, "read_source", None)
        if not source_files or not reader or not query.strip():
            return []
        matches: list[dict[str, Any]] = []
        paths = [path] if path else await source_files()
        for path in paths:
            try:
                text = reader(path)
            except (OSError, ValueError, UnicodeError):
                continue
            for line, value in enumerate(text.splitlines(), 1):
                if query.casefold() in value.casefold():
                    hit = re.search(re.escape(query), value, re.IGNORECASE)
                    offset = max(0, hit.start() - 100) if hit else 0
                    match = {"path": path, "line": line, "text": value[offset:offset + 300]}
                    if offset:
                        match["char_start"] = offset
                    matches.append(match)
                    if len(matches) >= 60:
                        return matches
        return matches
