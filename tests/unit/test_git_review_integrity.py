from __future__ import annotations

import asyncio
import subprocess
import threading
from unittest.mock import AsyncMock

import pytest

from agentlab.adapters.events import InProcessEventBus
from agentlab.adapters.workspace import GitWorkspace
from agentlab.core.budget import BudgetExceeded, estimate_cents
from agentlab.core.llm.retry import ParallelFailure
from agentlab.core.loop.arbiter import arbitrate
from agentlab.core.schemas import AgentInput, AgentResult, FileEdit, RunStatus, Usage, Verdict
from tests.conftest import finding, verdict
from tests.unit.test_driver import make_driver


async def test_oversize_baseline_rewritten_as_code_is_visible_and_index_unchanged(tmp_path):  # type: ignore[no-untyped-def]
    (tmp_path / "big.py").write_text("x" * 120_000)
    ws = GitWorkspace(tmp_path)
    await ws.ensure_repo()
    ws.begin_run()
    index = (tmp_path / ".git/index").read_bytes()
    ws.apply_edits([FileEdit(path="big.py", content="import os\nos.system('rm -rf ~')\n")])
    diff = await ws.diff()
    assert "big.py" in diff and "oversize -> text" in diff and "os.system('rm -rf ~')" in diff
    assert (tmp_path / ".git/index").read_bytes() == index


@pytest.mark.parametrize("body", [b"x" * 120_000, b"\0first"], ids=["oversize", "binary"])
async def test_nontext_change_and_deletion_have_visible_git_identity(tmp_path, body):  # type: ignore[no-untyped-def]
    path = tmp_path / "data.bin"
    path.write_bytes(body)
    ws = GitWorkspace(tmp_path)
    await ws.ensure_repo()
    ws.begin_run()
    assert await ws.diff() == ""
    path.write_bytes(body + b"changed")
    changed = await ws.diff()
    assert "data.bin" in changed and "new blob" in changed
    path.unlink()
    deleted = await ws.diff()
    assert "absent" in deleted and deleted != changed


async def test_binary_mode_change_has_real_git_mode_metadata(tmp_path):  # type: ignore[no-untyped-def]
    path = tmp_path / "data.bin"
    path.write_bytes(b"\0binary")
    path.chmod(0o644)
    ws = GitWorkspace(tmp_path)
    await ws.ensure_repo()
    ws.begin_run()
    path.chmod(0o755)
    diff = await ws.diff()
    assert "100644 100755" in diff


async def test_staged_user_changes_and_index_are_preserved(tmp_path):  # type: ignore[no-untyped-def]
    ws = GitWorkspace(tmp_path)
    await ws.ensure_repo()
    (tmp_path / "user.py").write_text("user staged content\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "user.py"], check=True)
    ws.begin_run()
    index = (tmp_path / ".git/index").read_bytes()
    ws.apply_edits([FileEdit(path="own.py", content="coder content\n")])
    diff = await ws.diff()
    assert "user.py" not in diff and "+coder content" in diff
    assert (tmp_path / ".git/index").read_bytes() == index


async def test_added_gitignored_file_is_still_reviewed(tmp_path):  # type: ignore[no-untyped-def]
    (tmp_path / ".gitignore").write_text("generated.py\n")
    ws = GitWorkspace(tmp_path)
    await ws.ensure_repo()
    ws.begin_run()
    ws.apply_edits([FileEdit(path="generated.py", content="actual code\n")])
    assert "+actual code" in await ws.diff()


async def test_detected_secret_change_is_marked_without_persisting_secret_blob(tmp_path):  # type: ignore[no-untyped-def]
    path = tmp_path / "source.py"
    path.write_text("value = 1\n")
    ws = GitWorkspace(tmp_path)
    await ws.ensure_repo()
    ws.begin_run()
    secret = "sk-" + "z" * 30
    path.write_text(secret)
    diff = await ws.diff()
    assert "redacted-secret" in diff and secret not in diff
    objects = subprocess.check_output(["git", "-C", str(tmp_path), "cat-file", "--batch-all-objects", "--batch"], env=ws._snapshot_env())
    assert secret.encode() not in objects


def test_conflicting_requirement_on_different_lines_escalates():
    a = finding(conf=.6).model_copy(update={"line": 10, "subject": "add-validation", "stance": "require"})
    b = finding(conf=.6).model_copy(update={"line": 12, "subject": "add-validation", "stance": "forbid"})
    decision = arbitrate([verdict("a", a), verdict("b", b)], .7)
    assert decision.reason == "reviewer_conflict"
    assert {f.line for f in decision.conflicts[0].findings} == {10, 12}


def test_unknown_subject_does_not_invalidate_verdict_and_logs_without_value(caplog):  # type: ignore[no-untyped-def]
    payload = verdict("a", finding()).model_dump()
    payload["findings"][0]["subject"] = "add-null-check"
    result = Verdict.model_validate(payload)
    assert result.findings[0].subject == "" and len(result.findings) == 1
    assert "unknown finding subject" in caplog.text and "add-null-check" not in caplog.text


def test_budget_estimate_ratios_change_reservation_not_usage_prices(cfg):  # type: ignore[no-untyped-def]
    alias = cfg.models.aliases["strong"]
    old = alias.model_copy(update={"estimate_input_tokens_per_byte": 1, "estimate_output_token_ratio": 1})
    assert estimate_cents(alias, 80_000) == pytest.approx(estimate_cents(old, 80_000) / 2)
    assert alias.cost_cents(100, 200) == old.cost_cents(100, 200)


async def test_async_creation_publishes_on_event_loop_with_global_subscriber(cfg, tmp_path):  # type: ignore[no-untyped-def]
    driver = await make_driver(cfg, tmp_path)
    loop_thread = threading.get_ident()
    baseline = driver.workspace.begin_run
    worker_threads = []
    def capture():  # type: ignore[no-untyped-def]
        worker_threads.append(threading.get_ident())
        baseline()
    driver.workspace.begin_run = capture
    bus = InProcessEventBus()
    original = bus.publish
    def publish(event):  # type: ignore[no-untyped-def]
        assert threading.get_ident() == loop_thread
        original(event)
    bus.publish = publish
    driver.bus = bus
    subscription = bus.subscribe("*")
    waiting = asyncio.create_task(anext(subscription))
    run = await driver.create_async("g")
    assert (await asyncio.wait_for(waiting, 1)).run_id == run.id
    assert worker_threads[0] != loop_thread
    await subscription.aclose()


async def test_partial_review_inputs_remain_frozen_across_memory_change_and_reject_clears_cache(cfg, tmp_path):  # type: ignore[no-untyped-def]
    driver = await make_driver(cfg, tmp_path)
    run = driver.create("g", budget_cents=200)
    run.status = RunStatus.REVIEWING
    roles = cfg.reviewer_roles
    memory = {"memory": "old"}
    driver.hooks.context_for = AsyncMock(side_effect=lambda *args: memory.copy())
    inp = AgentInput(run_id=run.id, iteration=1, goal="g")
    result = AgentResult(role=roles[0], output=Verdict(reviewer_id="r", verdict="APPROVE"),
                         alias="strong", model="test", usage=Usage(cost_cents=1))
    async def partial(inputs, *args):  # type: ignore[no-untyped-def]
        raise ParallelFailure(BudgetExceeded("pause"), [result])
    driver.runtime.run_parallel = partial
    with pytest.raises(BudgetExceeded):
        await driver._agents(run, roles, inp, Verdict)
    memory["memory"] = "new"
    async def remaining(inputs, *args):  # type: ignore[no-untyped-def]
        assert roles[0] not in inputs
        assert all(i.context["memory"] == "old" for i in inputs.values())
        raise ParallelFailure(BudgetExceeded("pause"), [])
    driver.runtime.run_parallel = remaining
    with pytest.raises(BudgetExceeded):
        await driver._agents(run, roles, inp, Verdict)
    assert driver.hooks.context_for.await_count == 3
    driver._escalate(run, "budget_exceeded", {"required_budget_cents": 300}, on_approve=RunStatus.REVIEWING)
    driver.decide(run.id, "reject", feedback="replan")
    assert not driver._completed_agents and not driver._agent_inputs
