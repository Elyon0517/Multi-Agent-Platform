from pathlib import Path

import pytest

from agentlab.adapters.runtime.fake import FakeRuntime
from agentlab.adapters.workspace import GitWorkspace
from agentlab.core.llm.retry import ParallelFailure
from agentlab.core.loop.driver import Driver
from agentlab.core.schemas import CoderOutput, FileEdit, GateMode, GateResult, RunStatus
from agentlab.demo import demo_scripts
from tests.unit.test_driver import make_driver


class PassingGate:
    language = "python"

    def __init__(self):
        self.calls = []
        self.mutate_on = None

    async def run(self, workspace, mode):
        self.calls.append(mode)
        if mode == self.mutate_on:
            self.mutate_on = None
            (workspace / "calc.py").write_text((workspace / "calc.py").read_text() + "# changed by check\n")
        return GateResult(language=self.language, mode=mode, passed=True, steps=[])


async def prepared(cfg, tmp_path, with_gate=True):
    driver = await make_driver(cfg, tmp_path, {
        "coder": lambda _: CoderOutput(edits=[FileEdit(
            path="calc.py", content='def add(a, b):\n    """Add."""\n    return a + b\n',
        )]),
    })
    driver.gate = PassingGate() if with_gate else None
    run = driver.create("fix add")
    await driver._planning(run)
    await driver._coding(run)
    return driver, run


def restore(driver):
    data = driver.store.checkpoint(driver.store.list_runs()[0].id)
    ws = GitWorkspace(driver.workspace.root, snapshot_dir=Path(data["workspace"]["snapshot_dir"]))
    ws.restore_state(data["workspace"])
    restored = Driver(driver.cfg, driver.store, driver.blobs, driver.bus,
                      FakeRuntime(demo_scripts()), driver.gate, ws)
    restored.restore_checkpoint(data)
    return restored


@pytest.mark.parametrize("with_gate", [True, False])
async def test_signoff_rejects_changed_source_and_rechecks_without_overwriting(cfg, tmp_path, with_gate):
    driver, run = await prepared(cfg, tmp_path, with_gate)
    run = await driver.run(run.id)
    original = driver.store.pending_approval(run.id)
    old_revision = original.payload["revision_id"]
    # This file was not in the original Coder diff; the whole source revision must be checked.
    path = driver.workspace.root / "test_calc.py"
    path.write_text(path.read_text() + "# user edit after review\n")
    restored = restore(driver)
    run = restored.decide(run.id, "approve")
    assert run.status == RunStatus.WAITING_HUMAN
    stale = restored.store.pending_approval(run.id)
    assert stale.reason == "workspace_changed" and stale.id != original.id
    assert not restored.store.checkpoint(run.id)["results"]
    restored.decide(run.id, "approve")
    run = await restored.run(run.id)
    fresh = restored.store.pending_approval(run.id)
    assert fresh.reason == "signoff" and fresh.payload["revision_id"] != old_revision
    revision = fresh.payload["revision_id"]
    assert "user edit after review" in path.read_text()
    assert not any(role == "coder" for role, _ in restored.runtime.calls)
    assert {role for role, _ in restored.runtime.calls} == set(driver.cfg.reviewer_roles)
    it = restored.store.iterations(run.id)[-1]
    assert it.revision_id == revision and all(v.revision_id == revision for v in it.verdicts)
    assert it.gate_result is None or it.gate_result.revision_id == revision
    artifacts = restored.store.artifacts(run.id)
    latest_diff = [a for a in artifacts if a.kind == "diff"][-1]
    assert latest_diff.revision_id == revision
    assert "user edit after review" in restored.blobs.get(latest_diff.content_ref)
    assert all(a.revision_id == revision for a in artifacts[artifacts.index(latest_diff):]
               if a.kind in {"gate", "review", "arbiter"})
    assert restored.decide(run.id, "approve").status == RunStatus.DONE


@pytest.mark.parametrize("changed", [True, False])
@pytest.mark.parametrize("with_gate", [True, False])
async def test_partial_reviewer_restore_reuses_only_matching_revision(cfg, tmp_path, changed, with_gate):
    driver, run = await prepared(cfg, tmp_path, with_gate)
    if with_gate:
        await driver._gating(run)
    runtime = driver.runtime
    first = driver.cfg.reviewer_roles[0]

    async def partial(inputs, output_type, ctx):
        result = await runtime.run_agent(first, inputs[first], output_type, ctx)
        ctx.on_result(result)
        raise ParallelFailure(RuntimeError("review interrupted"), [result])

    driver.runtime.run_parallel = partial
    run = await driver.run(run.id)
    assert run.paused_reason == "execution_error"
    checkpoint = driver.store.checkpoint(run.id)
    old_revision = checkpoint["options"]["revision_id"]
    assert checkpoint["results"][0]["result"]["output"]["revision_id"] == old_revision
    if changed:
        path = driver.workspace.root / "calc.py"
        path.write_text(path.read_text() + "# user edit while paused\n")
    restored = restore(driver)
    resumed = restored.decide(run.id, "approve")
    if changed:
        assert resumed.paused_reason == "workspace_changed"
        assert not restored.store.checkpoint(run.id)["inputs"]
        assert not restored.store.checkpoint(run.id)["results"]
        restored.decide(run.id, "approve")
    run = await restored.run(run.id)
    assert run.paused_reason == "signoff"
    calls = [role for role, _ in restored.runtime.calls]
    expected = set(driver.cfg.reviewer_roles) if changed else set(driver.cfg.reviewer_roles) - {first}
    assert set(calls) == expected and len(calls) == len(expected)
    revision = restored.store.pending_approval(run.id).payload["revision_id"]
    assert (revision != old_revision) == changed
    assert all(v.revision_id == revision for v in restored.store.iterations(run.id)[-1].verdicts)
    if with_gate:
        assert driver.gate.calls.count(GateMode.FAST) == (2 if changed else 1)


@pytest.mark.parametrize("mode", [GateMode.FAST, GateMode.FULL])
async def test_source_changed_during_gate_invalidates_results(cfg, tmp_path, mode):
    driver, run = await prepared(cfg, tmp_path)
    driver.gate.mutate_on = mode
    run = await driver.run(run.id)
    assert run.paused_reason == "workspace_changed"
    if mode == GateMode.FAST:
        assert not driver.store.artifacts(run.id, "gate")
    else:
        assert all(a.revision_id != driver.store.pending_approval(run.id).payload["current_revision_id"]
                   for a in driver.store.artifacts(run.id, "gate"))
    assert not driver.store.checkpoint(run.id)["results"]


async def test_source_changed_during_review_cannot_reach_signoff(cfg, tmp_path):
    driver, run = await prepared(cfg, tmp_path)
    original = driver.runtime.run_parallel

    async def mutate(inputs, output_type, ctx):
        results = await original(inputs, output_type, ctx)
        path = driver.workspace.root / "calc.py"
        path.write_text(path.read_text() + "# changed during review\n")
        return results

    driver.runtime.run_parallel = mutate
    run = await driver.run(run.id)
    assert run.paused_reason == "workspace_changed"
    assert not driver.store.artifacts(run.id, "review")
    assert not driver.store.checkpoint(run.id)["results"]


async def test_legacy_unbound_results_require_fresh_review(cfg, tmp_path):
    driver, run = await prepared(cfg, tmp_path, with_gate=False)
    driver.recovery_options.pop("revision_id")
    driver._checkpoint(run)
    run = await driver.run(run.id)
    assert run.paused_reason == "workspace_changed"
    assert not any(role in cfg.reviewer_roles for role, _ in driver.runtime.calls)


async def test_revalidating_legacy_signoff_does_not_reuse_stale_oscillation_history(cfg, tmp_path):
    driver, run = await prepared(cfg, tmp_path)
    run = await driver.run(run.id)
    assert run.paused_reason == "signoff"
    driver.recovery_options.pop("revision_id")
    driver._checkpoint(run)
    restored = restore(driver)
    run = restored.decide(run.id, "approve")
    assert run.paused_reason == "workspace_changed"
    restored.decide(run.id, "approve")
    run = await restored.run(run.id)
    assert run.paused_reason == "signoff"
    assert len(restored.runtime.calls) == len(cfg.reviewer_roles)
