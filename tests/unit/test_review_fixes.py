from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from agentlab.adapters.gates.config_gate import ConfigGate
from agentlab.adapters.runtime.fake import FakeRuntime
from agentlab.adapters.sandbox.local import LocalSandbox
from agentlab.api.app import create_app
from agentlab.core.config import GateCfg
from agentlab.core.ports import RunBusy
from agentlab.core.schemas import CoderOutput, GateMode, RunStatus
from agentlab.demo import demo_gate_cfg, demo_scripts, seed_demo_workspace
from tests.unit.test_evidence_contract import contract, files
from tests.unit.test_memory_project import _svc


async def test_resumed_run_can_be_cancelled_and_duplicate_resume_keeps_original_task(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    driver = svc.driver(seed_demo_workspace(tmp_path / "ws"), "fake", "python")
    await driver.workspace.ensure_repo()
    run = await driver.create_async("Resume and cancel")
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def blocked(_run):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    driver._handlers[RunStatus.PLANNING] = blocked
    monkeypatch.setattr(type(svc), "restore_driver", lambda self, run_id: driver)
    transport = httpx.ASGITransport(app=create_app(svc))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        request = asyncio.create_task(client.post(f"/runs/{run.id}/resume"))
        try:
            await asyncio.wait_for(started.wait(), 5)
            duplicate = await client.post(f"/runs/{run.id}/resume")
            assert duplicate.status_code == 409
            assert not stopped.is_set()
            response = await client.post(f"/runs/{run.id}/cancel")
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "CANCELLED"
            assert stopped.is_set()
            resumed = await request
            assert resumed.status_code == 409
            assert resumed.json()["detail"] == "run execution was cancelled"
            assert svc.store.get_run(run.id).status == RunStatus.CANCELLED
        finally:
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)
            driver.workspace.close()


async def test_resume_still_waits_for_result(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    driver = svc.driver(seed_demo_workspace(tmp_path / "ws"), "fake", "python")
    await driver.workspace.ensure_repo()
    run = await driver.create_async("Resume to approval")

    async def pause(current):
        driver._escalate(current, "test_pause", {})

    driver._handlers[RunStatus.PLANNING] = pause
    monkeypatch.setattr(type(svc), "restore_driver", lambda self, run_id: driver)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(svc)), base_url="http://test") as client:
        response = await client.post(f"/runs/{run.id}/resume")
        assert response.status_code == 200
        assert response.json()["status"] == "WAITING_HUMAN"
    driver.workspace.close()


@pytest.mark.parametrize("occupied", ["active_run", "workspace_lock"])
async def test_report_revision_rejects_busy_workspace_without_changing_report(tmp_path, occupied):
    svc = _svc(tmp_path)
    root = seed_demo_workspace(tmp_path / "ws")
    files(root)
    driver = svc.driver(root, "fake", "python")
    scripts = demo_scripts()
    scripts["coder"] = lambda inp: CoderOutput(edits=[], report="Read-only report")
    driver.runtime = FakeRuntime(scripts)
    driver.runtime_factory = None
    await driver.workspace.ensure_repo()
    run = await driver.run((await driver.create_async("Read-only report")).id)
    assert run.status == RunStatus.DONE
    restored = svc.restore_driver(run.id)
    before = svc.store.get_run(run.id).model_dump()
    checkpoint = svc.store.checkpoint(run.id)
    artifacts = svc.store.artifacts(run.id)
    begin = restored.workspace.begin_run
    restored.workspace.begin_run = lambda: pytest.fail("must not reset snapshot while busy")
    try:
        if occupied == "active_run":
            await driver.create_async("Another active run")
            with pytest.raises(RunBusy):
                restored.revise_report(run.id, "Add evidence", contract())
        else:
            with svc.store.lock_run("workspace:" + str(restored.workspace.root)), pytest.raises(RunBusy):
                restored.revise_report(run.id, "Add evidence", contract())
        assert svc.store.get_run(run.id).model_dump() == before
        assert svc.store.checkpoint(run.id) == checkpoint
        assert svc.store.artifacts(run.id) == artifacts
    finally:
        restored.workspace.begin_run = begin
        restored.workspace.close()
        driver.workspace.close()


@pytest.mark.parametrize("mode", list(GateMode))
async def test_gate_with_no_checks_for_mode_fails_without_running_commands(tmp_path, mode):
    cfg = demo_gate_cfg()
    other = GateMode.FULL if mode == GateMode.FAST else GateMode.FAST
    for step in cfg.steps:
        step.modes = [other]
    sandbox = LocalSandbox()
    sandbox.exec = AsyncMock()
    gate = ConfigGate(cfg, sandbox)
    with pytest.raises(ValueError, match=f"no checks configured for {mode.value}"):
        await gate.run(tmp_path, mode)
    sandbox.exec.assert_not_called()


@pytest.mark.parametrize("empty", ["steps", "modes"])
def test_gate_configuration_rejects_empty_checks(empty):
    data = demo_gate_cfg().model_dump()
    if empty == "steps":
        data["steps"] = []
    else:
        data["steps"][0]["modes"] = []
    with pytest.raises(ValidationError):
        GateCfg.model_validate(data)
