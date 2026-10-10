from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from agentlab.adapters.events import InProcessEventBus
from agentlab.adapters.gates.config_gate import ConfigGate
from agentlab.adapters.runtime.fake import FakeRuntime
from agentlab.adapters.sandbox.local import LocalSandbox
from agentlab.adapters.store.blobs import FileBlobStore
from agentlab.adapters.store.memory import InMemoryStore
from agentlab.adapters.workspace import GitWorkspace
from agentlab.core.config import AppConfig
from agentlab.core.loop.driver import Driver
from agentlab.core.schemas import (
    AgentInput,
    CoderOutput,
    EventType,
    FileEdit,
    Finding,
    RunStatus,
    Severity,
    Verdict,
)
from agentlab.demo import demo_gate_cfg, demo_scripts, seed_demo_workspace

Script = Callable[[AgentInput], BaseModel]


async def make_driver(cfg: AppConfig, tmp: Path, scripts: dict[str, Script] | None = None) -> Driver:
    ws = GitWorkspace(seed_demo_workspace(tmp / "ws"))
    await ws.ensure_repo()
    return Driver(cfg, InMemoryStore(), FileBlobStore(tmp / "blobs"), InProcessEventBus(),
                  FakeRuntime({**demo_scripts(), **(scripts or {})}), ConfigGate(demo_gate_cfg(), LocalSandbox()), ws)


async def test_demo_converges_to_human_then_done(cfg: AppConfig, tmp_path: Path) -> None:
    d = await make_driver(cfg, tmp_path)
    run = await d.run(d.create("fix add").id)
    assert run.status == RunStatus.WAITING_HUMAN and run.paused_reason == "signoff"
    run = d.decide(run.id, "approve")
    assert run.status == RunStatus.DONE
    types = [e.type for e in d.store.events(run.id)]
    assert types.count(EventType.GATE_FINISHED) >= 3 and EventType.ARBITER_DECISION in types


async def test_coder_stuck_triggers_oscillation(cfg: AppConfig, tmp_path: Path) -> None:
    def stuck(_: AgentInput) -> BaseModel:
        return CoderOutput(edits=[FileEdit(path="calc.py", content="def add(a, b):\n    return 0\n")])

    d = await make_driver(cfg, tmp_path, {"coder": stuck})
    run = await d.run(d.create("fix add").id)
    assert run.status == RunStatus.WAITING_HUMAN and run.paused_reason == "oscillation_detected"


async def test_max_iter_escalates(cfg: AppConfig, tmp_path: Path) -> None:
    counter = {"n": 0}

    def wandering(_: AgentInput) -> BaseModel:
        counter["n"] += 1
        return CoderOutput(edits=[FileEdit(path="calc.py", content=f"def add(a, b):\n    return {counter['n']}\n")])

    d = await make_driver(cfg, tmp_path, {"coder": wandering})
    run = await d.run(d.create("fix add", max_iter=3).id)
    assert run.paused_reason == "max_iter_exceeded" and len(d.store.iterations(run.id)) == 3


async def test_budget_pauses_and_resumes(cfg: AppConfig, tmp_path: Path) -> None:
    d = await make_driver(cfg, tmp_path)
    run = await d.run(d.create("fix add", budget_cents=0.15).id)
    assert run.paused_reason == "budget_exceeded"
    paused_at = d.store.pending_approval(run.id).on_approve  # type: ignore[union-attr]
    run = d.decide(run.id, "approve", budget_cents=100)
    assert run.status == paused_at
    run = await d.run(run.id)
    assert run.status == RunStatus.WAITING_HUMAN and run.paused_reason == "signoff"


async def test_reject_feeds_back_to_coder(cfg: AppConfig, tmp_path: Path) -> None:
    seen: list[str | None] = []
    base = demo_scripts()["coder"]

    def coder(inp: AgentInput) -> BaseModel:
        seen.append(inp.feedback)
        return base(inp)

    d = await make_driver(cfg, tmp_path, {"coder": coder})
    run = await d.run(d.create("fix add").id)
    d.decide(run.id, "reject", feedback="rename it")
    await d.run(run.id)
    assert "rename it" in seen


async def test_reviewer_conflict_escalates(cfg: AppConfig, tmp_path: Path) -> None:
    def rev(sev: Severity, issue: str) -> Script:
        return lambda _: Verdict(reviewer_id="x", verdict="REQUEST_CHANGES", findings=[
            Finding(severity=sev, category="correctness", file="calc.py", line=2, issue=issue, confidence=0.6, subject="lock",
                    stance="require" if sev.is_hard else "forbid")])

    d = await make_driver(cfg, tmp_path, {
        "correctness-reviewer": rev(Severity.MAJOR, "must lock"),
        "arch-reviewer": rev(Severity.NIT, "lock harmful"),
    })
    run = await d.run(d.create("fix add").id)
    assert run.paused_reason == "reviewer_conflict"


async def test_workspace_escape_blocked(tmp_path: Path) -> None:
    import pytest

    from agentlab.adapters.workspace import WorkspaceEscape

    ws = GitWorkspace(tmp_path)
    for bad in ("../x.py", ".git/config", "/etc/passwd"):
        with pytest.raises(WorkspaceEscape):
            ws.apply_edits([FileEdit(path=bad, content="x")])


async def test_agents_receive_current_source_after_each_edit(cfg: AppConfig, tmp_path: Path) -> None:
    scripts = demo_scripts()
    seen: dict[str, list[str]] = {}

    def capture(role: str) -> Script:
        def script(inp: AgentInput) -> BaseModel:
            seen.setdefault(role, []).append(inp.context["files"]["calc.py"])
            return scripts[role](inp)
        return script

    d = await make_driver(cfg, tmp_path, {role: capture(role) for role in scripts})
    run = await d.run(d.create("fix add").id)
    assert run.paused_reason == "signoff"
    assert "return a - b" in seen["coder"][0]
    assert "return a * b" in seen["coder"][1]
    assert all("return a + b" in text for text in seen["correctness-reviewer"])
