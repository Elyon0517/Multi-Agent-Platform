"""Structured proposals with deterministic scope and version protection."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from agentlab.core.memory.store import GLOBAL, InMemoryMemoryStore, MemoryItem, MemoryKind
from agentlab.core.schemas import Strict, normalize_text, utcnow


class MemoryOp(Strict):
    action: Literal["add", "update", "retire"]
    namespace: str = "project"
    target_id: str | None = None
    text: str = Field(default="", max_length=4000)


class MemoryOps(Strict):
    operations: list[MemoryOp] = Field(default_factory=list, max_length=30)


async def apply_ops(
    memory: InMemoryMemoryStore, project_id: str, run_id: str, roles: set[str],
    supplied: list[MemoryItem], proposals: MemoryOps,
) -> list[str]:
    allowed = {GLOBAL, "project", *(f"agent:{role}" for role in roles)}
    supplied_ids = {i.id for i in supplied}
    touched: set[str] = set()
    applied: list[str] = []
    for op in proposals.operations:
        if op.namespace not in allowed:
            continue
        owner = None if op.namespace == GLOBAL else project_id
        # One refreshed pool per operation: subsequent refreshes replace clean cached objects.
        # Keep validation and mutation attached to the same live version.
        pool = memory.items_in(op.namespace, project_id)
        target = next((i for i in pool if i.id == op.target_id), None)
        if op.action != "add":
            if (target is None or target.id not in supplied_ids or target.id in touched
                    or target.namespace != op.namespace or target.project_id != owner
                    or target.pinned or target.kind == MemoryKind.DOCUMENT or target.valid_to is not None):
                continue
        elif op.target_id is not None:
            continue
        if op.action == "retire":
            assert target is not None
            target.valid_to = utcnow().isoformat()
            touched.add(target.id)
            applied.append(target.id)
            continue
        text = op.text.strip()
        if not text:
            continue
        duplicate = next((i for i in pool
                          if normalize_text(i.text) == normalize_text(text) and i.id != op.target_id), None)
        if duplicate:
            continue
        item = MemoryItem(project_id=owner, namespace=op.namespace, kind=MemoryKind.SEMANTIC,
                          text=text, source="summarizer", source_run_id=run_id)
        await memory.add([item], embed=False)
        if op.action == "update":
            assert target is not None
            target.valid_to, target.superseded_by = utcnow().isoformat(), item.id
            touched.add(target.id)
        applied.append(item.id)
    memory.flush()
    return applied
