import hashlib
from pathlib import Path

import pytest

from agentlab.adapters.runtime.fake import FakeRuntime
from agentlab.adapters.workspace import GitWorkspace
from agentlab.core.loop.driver import Driver
from agentlab.core.ports import EditConflict
from agentlab.core.schemas import AgentResult, CoderOutput, FileEdit, RunStatus
from agentlab.demo import demo_scripts
from tests.unit.test_driver import make_driver


class ProcessDied(BaseException):
    pass


EDITS = [FileEdit(path="a.py", content="a = 2\n"), FileEdit(path="b.py", content="b = 2\n")]


async def setup(cfg, tmp_path):
    driver = await make_driver(cfg, tmp_path, {"coder": lambda _: CoderOutput(edits=EDITS)})
    driver.gate = None
    (driver.workspace.root / "a.py").write_text("a = 1\n")
    (driver.workspace.root / "b.py").write_text("b = 1\n")
    run = driver.create("update a and b")
    return driver, run, driver.workspace.edit_baseline()


def restore(driver, run, runtime=None):
    data = driver.store.checkpoint(run.id)
    ws = GitWorkspace(driver.workspace.root, snapshot_dir=Path(data["workspace"]["snapshot_dir"]))
    ws.restore_state(data["workspace"])
    result = Driver(driver.cfg, driver.store, driver.blobs, driver.bus,
                    runtime or FakeRuntime(demo_scripts()), None, ws)
    result.restore_checkpoint(data)
    return result


@pytest.mark.parametrize("lost_ack", [False, True])
async def test_multifile_recovery_skips_applied_and_replays_only_pending(cfg, tmp_path, monkeypatch, lost_ack):
    driver, run, baseline = await setup(cfg, tmp_path)
    write = driver.workspace.apply_edits
    put = driver.store.put_record
    paths = []

    def fail_second(edits, expected_hashes=None):
        paths.extend(e.path for e in edits)
        if len(paths) == 2:
            raise ProcessDied()
        return write(edits, expected_hashes)

    def fail_ack(kind, key, data):
        if kind == "edit_operation" and any(f["status"] == "applied" for f in data["files"]):
            raise ProcessDied()
        return put(kind, key, data)

    with monkeypatch.context() as patch:
        patch.setattr(driver.workspace, "apply_edits", fail_second)
        if lost_ack:
            patch.setattr(driver.store, "put_record", fail_ack)
        with pytest.raises(ProcessDied):
            driver.edit_journal.apply(run, "scope", "final", EDITS, baseline, "coder_output")
    assert (driver.workspace.root / "a.py").read_text() == "a = 2\n"
    assert (driver.workspace.root / "b.py").read_text() == "b = 1\n"
    recorded = driver.store.records("edit_operation")[0]
    assert recorded["files"][0]["status"] == ("pending" if lost_ack else "applied")
    assert recorded["files"][0]["before_hash"] == hashlib.sha256(b"a = 1\n").hexdigest()
    assert recorded["files"][0]["after_hash"] == hashlib.sha256(b"a = 2\n").hexdigest()
    restored = restore(driver, run)
    original = restored.workspace.apply_edits
    replayed = []

    def observe(edits, expected_hashes=None):
        replayed.extend(e.path for e in edits)
        return original(edits, expected_hashes)

    monkeypatch.setattr(restored.workspace, "apply_edits", observe)
    restored.edit_journal.apply(run, "scope", "final", EDITS, baseline, "coder_output")
    restored.edit_journal.apply(run, "scope", "final", EDITS, baseline, "coder_output")
    assert replayed == ["b.py"]
    assert len(driver.store.records("edit_operation")) == 1
    assert driver.store.records("edit_operation")[0]["status"] == "applied"


async def test_partial_batch_conflict_does_not_write_remaining_files(cfg, tmp_path, monkeypatch):
    driver, run, baseline = await setup(cfg, tmp_path)
    original = driver.workspace.apply_edits

    def fail(edits, expected_hashes=None):
        if edits[0].path == "b.py":
            raise ProcessDied()
        return original(edits, expected_hashes)

    with monkeypatch.context() as patch:
        patch.setattr(driver.workspace, "apply_edits", fail)
        with pytest.raises(ProcessDied):
            driver.edit_journal.apply(run, "scope", "final", EDITS, baseline, "coder_output")
    (driver.workspace.root / "a.py").write_text("# human change\na = 9\n")
    restored = restore(driver, run)
    for _ in range(2):
        with pytest.raises(EditConflict) as exc:
            restored.edit_journal.apply(run, "scope", "final", EDITS, baseline, "coder_output")
        assert exc.value.paths == ["a.py"]
        assert (restored.workspace.root / "a.py").read_text() == "# human change\na = 9\n"
        assert (restored.workspace.root / "b.py").read_text() == "b = 1\n"
    record = driver.store.records("edit_operation")[0]
    assert [f["status"] for f in record["files"]] == ["conflict", "pending"]
    # Explicitly restoring a recorded result resolves the conflict; only b remains to apply.
    (restored.workspace.root / "a.py").write_text(EDITS[0].content)
    restored.edit_journal.recover(run, "scope")
    assert (restored.workspace.root / "b.py").read_text() == EDITS[1].content


async def test_consecutive_tool_writes_supersede_older_intents_without_rewinding(cfg, tmp_path, monkeypatch):
    driver, run, baseline = await setup(cfg, tmp_path)
    first = [FileEdit(path="a.py", content="a = 2\n")]
    second = [FileEdit(path="a.py", content="a = 3\n")]
    journal = driver.edit_journal
    journal.apply(run, "scope", "tool:one", first, baseline, "workspace_write")
    journal.apply(run, "scope", "tool:two", second, baseline, "workspace_write")
    operations = driver.store.records("edit_operation")
    assert operations[1]["files"][0]["before_hash"] == operations[0]["files"][0]["after_hash"]
    restored = restore(driver, run)

    def forbidden(*args, **kwargs):
        raise AssertionError("already applied or superseded operations must not write")

    monkeypatch.setattr(restored.workspace, "apply_edits", forbidden)
    restored.edit_journal.apply(run, "scope", "tool:one", first, baseline, "workspace_write")
    restored.edit_journal.apply(run, "scope", "final", second, baseline, "coder_output")
    assert (restored.workspace.root / "a.py").read_text() == "a = 3\n"
    with pytest.raises(EditConflict):
        restored.edit_journal.apply(run, "scope", "tool:one", second, baseline, "workspace_write")


async def test_ignored_applied_file_is_still_in_diff_after_recovery(cfg, tmp_path):
    driver, run, baseline = await setup(cfg, tmp_path)
    (driver.workspace.root / ".gitignore").write_text("generated.py\n")
    edits = [FileEdit(path="generated.py", content="generated = 1\n")]
    driver.edit_journal.apply(run, "scope", "tool:x", edits, baseline, "workspace_write")
    # Restore the pre-write checkpoint, whose edited_paths did not include this ignored file.
    restored = restore(driver, run)
    assert "generated.py" not in restored.workspace.export_state()["edited_paths"]
    restored.edit_journal.recover(run, "scope")
    assert "+generated = 1" in await restored.workspace.diff()


async def test_journal_commit_failure_prevents_any_file_write(cfg, tmp_path, monkeypatch):
    driver, run, baseline = await setup(cfg, tmp_path)

    def fail(*args, **kwargs):
        raise OSError("database unavailable")

    monkeypatch.setattr(driver.store, "put_record", fail)
    with pytest.raises(OSError):
        driver.edit_journal.apply(run, "scope", "final", EDITS, baseline, "coder_output")
    assert (driver.workspace.root / "a.py").read_text() == "a = 1\n"
    assert (driver.workspace.root / "b.py").read_text() == "b = 1\n"


async def test_atomic_file_replacement_does_not_leave_half_written_content(cfg, tmp_path, monkeypatch):
    from agentlab.adapters import workspace

    driver, run, baseline = await setup(cfg, tmp_path)

    original_replace = workspace.os.replace

    def fail(source, target):
        if Path(source).name.startswith(".agentlab-write-"):
            raise ProcessDied()
        return original_replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(workspace.os, "replace", fail)
        with pytest.raises(ProcessDied):
            driver.edit_journal.apply(run, "scope", "final", EDITS, baseline, "coder_output")
    assert (driver.workspace.root / "a.py").read_text() == "a = 1\n"
    assert not list(driver.workspace.root.glob(".agentlab-write-*"))
    driver.edit_journal.recover(run, "scope")
    assert (driver.workspace.root / "a.py").read_text() == EDITS[0].content


async def test_driver_recovery_preserves_human_edit_and_does_not_rebill_coder(cfg, tmp_path, monkeypatch):
    driver, run, _ = await setup(cfg, tmp_path)
    await driver._planning(run)
    original = driver.workspace.apply_edits

    def fail(edits, expected_hashes=None):
        if edits[0].path == "b.py":
            raise ProcessDied()
        return original(edits, expected_hashes)

    with monkeypatch.context() as patch:
        patch.setattr(driver.workspace, "apply_edits", fail)
        with pytest.raises(ProcessDied):
            await driver._coding(run)
    paid = driver.store.get_run(run.id).cost_cents
    (driver.workspace.root / "a.py").write_text("a = 99  # human\n")
    restored = restore(driver, run)
    for attempt in range(2):
        if attempt:
            restored.decide(run.id, "approve")
        result = await restored.run(run.id)
        assert result.paused_reason == "edit_conflict"
        assert restored.store.pending_approval(run.id).payload["paths"] == ["a.py"]
        assert (restored.workspace.root / "a.py").read_text() == "a = 99  # human\n"
        assert (restored.workspace.root / "b.py").read_text() == "b = 1\n"
    assert not restored.runtime.calls and result.cost_cents == paid
    old_scope = next(iter(restored.recovery_options["write_scopes"].values()))["id"]
    restored.decide(run.id, "reject", feedback="preserve my a.py edit and replan")
    current = restored.store.get_run(run.id)
    await restored._coding(current)
    assert (restored.workspace.root / "a.py").read_text() == "a = 99  # human\n"
    assert all(op["scope_id"] == old_scope for op in restored.store.records("edit_operation")
               if any(f["path"] == "a.py" for f in op["files"]))


@pytest.mark.parametrize("human_change", [False, True])
async def test_workspace_write_tool_recovery_uses_same_journal(cfg, tmp_path, human_change):
    driver, run, _ = await setup(cfg, tmp_path)

    class ToolCoder(FakeRuntime):
        def __init__(self, crash):
            super().__init__(demo_scripts())
            self.crash, self.coder_calls = crash, 0

        async def run_agent(self, role, inp, output_type, ctx):
            if role != "coder":
                return await super().run_agent(role, inp, output_type, ctx)
            self.coder_calls += 1
            _specs, execute = ctx.tool_factory("coder")
            ctx.record_tool({"role": "coder", "name": "workspace_write", "id": "same-tool-id", "status": "started"})
            await execute("workspace_write", EDITS[0].model_dump())
            if self.crash:
                raise ProcessDied()
            return AgentResult(role="coder", output=CoderOutput(edits=[]), alias="fake", model="fake")

    driver.runtime = ToolCoder(True)
    await driver._planning(run)
    with pytest.raises(ProcessDied):
        await driver._coding(run)
    if human_change:
        (driver.workspace.root / "a.py").write_text("a = 99  # human\n")
    runtime = ToolCoder(False)
    restored = restore(driver, run, runtime)
    if human_change:
        result = await restored.run(run.id)
        assert result.paused_reason == "edit_conflict" and runtime.coder_calls == 0
        assert (restored.workspace.root / "a.py").read_text() == "a = 99  # human\n"
    else:
        await restored._coding(restored.store.get_run(run.id))
        assert restored.store.get_run(run.id).status == RunStatus.REVIEWING
        assert runtime.coder_calls == 1
        assert len(restored.store.records("edit_operation")) == 1


async def test_change_between_coder_response_and_first_write_is_not_overwritten(cfg, tmp_path):
    driver, run, _ = await setup(cfg, tmp_path)
    await driver._planning(run)
    # Save the paid result before any write intent has been prepared.
    await driver._agent(run, "coder", driver._coder_input(run), CoderOutput)
    (driver.workspace.root / "a.py").write_text("a = 99  # human\n")
    restored = restore(driver, run)
    result = await restored.run(run.id)
    assert result.paused_reason == "edit_conflict"
    assert not restored.runtime.calls
    assert (restored.workspace.root / "a.py").read_text() == "a = 99  # human\n"
    assert (restored.workspace.root / "b.py").read_text() == "b = 1\n"


@pytest.mark.parametrize("human_change", [False, True])
async def test_completed_writes_before_stage_commit_are_rechecked_without_replay(cfg, tmp_path, monkeypatch, human_change):
    driver, run, _ = await setup(cfg, tmp_path)
    await driver._planning(run)

    def fail(*args):
        raise ProcessDied()

    with monkeypatch.context() as patch:
        patch.setattr(driver, "_bind_revision", fail)
        with pytest.raises(ProcessDied):
            await driver._coding(run)
    assert driver.store.records("edit_operation")[0]["status"] == "applied"
    if human_change:
        (driver.workspace.root / "a.py").write_text("a = 99  # human\n")
    restored = restore(driver, run)

    def forbidden(*args, **kwargs):
        raise AssertionError("completed writes must not replay")

    monkeypatch.setattr(restored.workspace, "apply_edits", forbidden)
    if human_change:
        result = await restored.run(run.id)
        assert result.paused_reason == "edit_conflict"
        assert (restored.workspace.root / "a.py").read_text() == "a = 99  # human\n"
    else:
        await restored._coding(restored.store.get_run(run.id))
        assert restored.store.get_run(run.id).status == RunStatus.REVIEWING
    assert not restored.runtime.calls


async def test_legacy_cached_coder_without_write_baseline_requires_replanning(cfg, tmp_path):
    driver, run, _ = await setup(cfg, tmp_path)
    await driver._planning(run)
    await driver._agent(run, "coder", driver._coder_input(run), CoderOutput)
    driver.recovery_options.pop("write_scopes")
    driver._checkpoint(run)
    restored = restore(driver, run)
    result = await restored.run(run.id)
    assert result.paused_reason == "edit_conflict"
    assert restored.store.pending_approval(run.id).payload["operation_id"] == "missing_write_baseline"
    assert (restored.workspace.root / "a.py").read_text() == "a = 1\n"
    assert not restored.runtime.calls
