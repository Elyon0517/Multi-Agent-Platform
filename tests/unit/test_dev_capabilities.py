import asyncio
import subprocess
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from agentlab.adapters.runtime.fake import FakeRuntime
from agentlab.api.app import create_app
from agentlab.core.project_config import ProjectSettings
from agentlab.core.schemas import CoderOutput, RunStatus
from agentlab.demo import demo_scripts, seed_demo_workspace
from tests.unit.test_memory_project import _svc


def _repo(path: Path) -> Path:
    ws = seed_demo_workspace(path)
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "i"]):
        subprocess.run(["git", "-C", str(ws), *args], check=True, capture_output=True)
    return ws


def _wait(client: TestClient, run_id: str, *statuses: str) -> dict:
    for _ in range(300):
        detail = client.get(f"/runs/{run_id}").json()
        if detail["run"]["status"] in statuses:
            return detail
        time.sleep(0.05)
    raise AssertionError(f"{run_id} never reached {statuses}")


async def test_an_empty_delivery_pauses_with_the_coders_reason_instead_of_being_reviewed(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    driver = svc.driver(seed_demo_workspace(tmp_path / "ws"), "fake", "python")
    scripts = demo_scripts()
    scripts["coder"] = lambda inp: CoderOutput(edits=[], report="Partial analysis", blocked_reason="cannot read the reference repository")
    driver.runtime = FakeRuntime(scripts)
    await driver.workspace.ensure_repo()
    run = await driver.create_async("port the MVP")
    run = await driver.run(run.id)
    assert run.status == RunStatus.WAITING_HUMAN
    approval = svc.store.pending_approval(run.id)
    assert approval.reason == "no_changes"
    assert approval.payload["blocked_reason"] == "cannot read the reference repository"
    assert not [s for s in svc.store.steps(run.id) if s.role.endswith("reviewer")]  # no budget spent on reviews


def test_stop_cancels_a_run_that_is_executing(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    repo = _repo(tmp_path / "repo")
    project = svc.projects.create("p", "fix add", str(repo))

    class SlowCoder(FakeRuntime):
        async def run_agent(self, role, inp, output_type, ctx):
            if role == "coder":
                await asyncio.sleep(60)
            return await super().run_agent(role, inp, output_type, ctx)

    svc.runtime = lambda name=None, cfg=None: SlowCoder(demo_scripts())
    with TestClient(create_app(svc)) as client:
        run = client.post("/runs", json={"goal": "fix add", "project_id": project.id, "runtime": "fake"}).json()
        _wait(client, run["id"], "CODING")
        stopped = client.post(f"/runs/{run['id']}/cancel")
        assert stopped.status_code == 200 and stopped.json()["status"] == "CANCELLED"
        assert client.post(f"/runs/{run['id']}/cancel").json()["status"] == "CANCELLED"  # idempotent
        assert Path(run["workspace"]) == repo.resolve()  # branch mode: the run worked in the repository


def test_project_check_commands_run_in_the_worktree_with_linked_dependencies(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    repo = _repo(tmp_path / "repo")
    (repo / "node_modules" / "pkg").mkdir(parents=True)
    check = f"{sys.executable} -c \"import pathlib; assert pathlib.Path('node_modules/pkg').is_dir(); print('checked')\""
    project = svc.projects.create("p", "fix add", str(repo))
    project.settings = ProjectSettings(check_commands=[check], workspace_mode="worktree")
    svc.projects.save(project)
    with TestClient(create_app(svc)) as client:
        run = client.post("/runs", json={"goal": "fix add", "project_id": project.id, "runtime": "fake"}).json()
        assert (Path(run["workspace"]) / "node_modules").is_symlink()
        detail = _wait(client, run["id"], "WAITING_HUMAN")
        assert detail["pending_approval"]["reason"] == "signoff"
        assert detail["pending_approval"]["payload"]["automated_checks"] == "passed"
        assert all(report["passed"] for report in detail["gate_reports"])
        assert detail["gate_reports"][0]["language"] == "project"


async def test_read_only_report_finishes_without_code_review(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    driver = svc.driver(seed_demo_workspace(tmp_path / "ws"), "fake", "python")
    scripts = demo_scripts()
    scripts["coder"] = lambda inp: CoderOutput(edits=[], report="Evidence and itemized scores")
    driver.runtime = FakeRuntime(scripts)
    await driver.workspace.ensure_repo()
    run = await driver.create_async("read-only scoring")
    run = await driver.run(run.id)
    assert run.status == RunStatus.DONE
    assert svc.store.pending_approval(run.id) is None
    report = svc.store.artifacts(run.id, "report")[-1]
    assert driver.blobs.get(report.content_ref) == "Evidence and itemized scores"
    assert not [s for s in svc.store.steps(run.id) if s.role.endswith("reviewer") or s.role == "arbiter"]


async def test_no_changes_approval_actually_retries_coder(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    driver = svc.driver(seed_demo_workspace(tmp_path / "ws"), "fake", "python")
    calls = []

    def coder(inp):
        calls.append(inp)
        if len(calls) == 1:
            return CoderOutput(edits=[], blocked_reason="temporary missing context")
        return CoderOutput(edits=[], report="Completed analysis")

    scripts = demo_scripts()
    scripts["coder"] = coder
    driver.runtime = FakeRuntime(scripts)
    await driver.workspace.ensure_repo()
    run = await driver.create_async("read-only scoring")
    run = await driver.run(run.id)
    assert run.status == RunStatus.WAITING_HUMAN
    driver.runtime_factory = None
    driver.decide(run.id, "approve")
    run = await driver.run(run.id)
    assert len(calls) == 2
    assert run.status == RunStatus.DONE


async def test_report_cannot_finish_with_pending_evidence_reads(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    driver = svc.driver(seed_demo_workspace(tmp_path / "ws"), "fake", "python")

    def coder(inp):
        driver.recovery_options['read_cursors'] = {'coder': {'pending': [
            {'path': 'evidence.txt', 'line_start': 190, 'char_start': 22, 'line_end': 250},
        ]}}
        return CoderOutput(edits=[], report='Premature final score')

    scripts = demo_scripts()
    scripts['coder'] = coder
    driver.runtime = FakeRuntime(scripts)
    await driver.workspace.ensure_repo()
    run = await driver.create_async('score evidence')
    run = await driver.run(run.id)
    assert run.status == RunStatus.WAITING_HUMAN
    assert svc.store.pending_approval(run.id).payload['pending_reads'][0]['line_start'] == 190
    assert not svc.store.artifacts(run.id, 'report')
