"""Semantic memory evals run the production hook, with explicit fake blind spots."""
from __future__ import annotations

import asyncio
import re
from typing import Any

from agentlab.adapters.runtime.fake import FakeRuntime
from agentlab.bootstrap import Services
from agentlab.core.memory.store import MemoryItem
from agentlab.core.memory.summarizer import MemoryOp, MemoryOps
from agentlab.core.schemas import Event, EventType, Finding, Iteration, Run, RunStatus, Verdict


async def evaluate_memory_case(svc: Services, case: dict[str, Any], runtime: str, timeout_s: float) -> dict[str, Any]:
    from agentlab.evaluation.baseline import check, scorecard

    project = svc.projects.create(case["id"], "Memory quality evaluation", "")
    seeds = [MemoryItem(project_id=None if item["namespace"] == "global" else project.id,
                        source="eval-seed", **item) for item in case.get("seed", [])]
    await svc.knowledge.memory.add(seeds, embed=False)
    original = svc.runtime
    run_ids: list[str] = []
    before = {i.id: i.model_dump() for i in seeds if i.pinned or i.kind == "document"}

    def fake_summary(inp: Any) -> MemoryOps:
        ops = []
        for proposal in case["fake_operations"]:
            data = dict(proposal)
            match = next((i for i in inp.context["existing_memory"]
                          if i["namespace"] == data["namespace"] and not i["pinned"] and i["kind"] != "document"), None)
            if data.pop("merge", False) and match:
                data.update(action="update", target_id=match["id"])
            ops.append(MemoryOp.model_validate(data))
        return MemoryOps(operations=ops)

    if runtime == "fake":
        svc.runtime = lambda name=None, cfg=None: FakeRuntime({"summarizer": fake_summary})  # type: ignore[method-assign]
    try:
        async with asyncio.timeout(timeout_s):
            for feedback in case["feedback"]:
                run = Run(goal="Extract lessons", project_id=project.id, workspace="", status=RunStatus.DONE)
                run_ids.append(run.id)
                svc.store.create_run(run)
                svc.store.append_event(Event(run_id=run.id, type=EventType.APPROVAL_DECIDED, actor="human",
                                             payload={"decision": "approve", "feedback": feedback}))
                if case.get("finding"):
                    finding = Finding.model_validate(case["finding"])
                    svc.store.add_iteration(Iteration(run_id=run.id, n=1, phase=RunStatus.REVIEWING,
                        diff_hash="eval", verdicts=[Verdict(reviewer_id="arch-reviewer", verdict="REQUEST_CHANGES",
                                                         summary="", findings=[finding])]))
                await svc.hooks.on_finished(run)
        active = [i for i in svc.knowledge.memory._items.values() if i.valid_to is None
                  and (i.project_id == project.id or i.namespace == "global")]
        checks = []
        attempts = [r for r in svc.store.records("summarization") if r.get("run_id") in run_ids]
        checks.append(check("invocation", len(attempts) == len(run_ids)
                            and all(a["status"] == "completed" for a in attempts), "Production on_finished hook"))
        for expectation in case["expect"]:
            matches = [i for i in active if re.search(expectation["pattern"], i.text, re.I)
                       and i.kind != "document" and not i.pinned]
            passed = len(matches) == expectation["count"] and all(
                i.namespace == expectation["namespace"] for i in matches)
            checks.append(check(expectation["name"], passed,
                                f"{len(matches)} active matches in {[i.namespace for i in matches]}", "memory"))
        if case.get("require_update"):
            history = [i for i in svc.knowledge.memory._items.values()
                       if i.project_id == project.id and i.valid_to and i.superseded_by]
            checks.append(check("versioned_merge", bool(history), "Old version retired with superseded_by", "memory"))
        checks.append(check("protected", all(svc.knowledge.memory._items[key].model_dump() == value
                                               for key, value in before.items()), "Pinned/document bytes preserved"))
        card = scorecard(case["id"], checks, int(runtime == "fake"))
        card["memory_evidence"] = [i.model_dump(exclude={"embedding"}) for i in svc.knowledge.memory._items.values()
                                   if i.project_id == project.id or i.source_run_id in run_ids]
        card["operations"] = attempts
        card["usage"] = [u for u in svc.store.usage_entries() if u["ref_id"] in run_ids]
        card["semantic_model_evaluated"] = runtime != "fake"
        return card
    except Exception as exc:
        return {**scorecard(case["id"], [check("execution", False, type(exc).__name__)], int(runtime == "fake")),
                "semantic_model_evaluated": runtime != "fake"}
    finally:
        svc.runtime = original  # type: ignore[method-assign]
        # Keep every case isolated, including global memories created by the previous case.
        doomed = {i.id for i in svc.knowledge.memory._items.values()
                  if i.source_run_id in run_ids or i.id in {seed.id for seed in seeds}}
        for identifier in doomed:
            svc.knowledge.memory._items.pop(identifier, None)
