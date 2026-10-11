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
    scripts["coder"] = lambda inp: CoderOutput(edits=[], blocked_reason="cannot read the reference repository")
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
        for _ in range(100):
            if not Path(run["workspace"]).exists():
                break
            time.sleep(0.05)
        assert not Path(run["workspace"]).exists()


def test_project_check_commands_run_in_the_worktree_with_linked_dependencies(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    repo = _repo(tmp_path / "repo")
    (repo / "node_modules" / "pkg").mkdir(parents=True)
    check = f"{sys.executable} -c \"import pathlib; assert pathlib.Path('node_modules/pkg').is_dir(); print('checked')\""
    project = svc.projects.create("p", "fix add", str(repo))
    project.settings = ProjectSettings(check_commands=[check])
    svc.projects.save(project)
    with TestClient(create_app(svc)) as client:
        run = client.post("/runs", json={"goal": "fix add", "project_id": project.id, "runtime": "fake"}).json()
        assert (Path(run["workspace"]) / "node_modules").is_symlink()
        detail = _wait(client, run["id"], "WAITING_HUMAN")
        assert detail["pending_approval"]["reason"] == "signoff"
        assert detail["pending_approval"]["payload"]["automated_checks"] == "passed"
        assert all(report["passed"] for report in detail["gate_reports"])
        assert detail["gate_reports"][0]["language"] == "project"
