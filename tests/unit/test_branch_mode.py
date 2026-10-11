import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentlab.api.app import create_app
from agentlab.core.schemas import RunStatus
from agentlab.demo import seed_demo_workspace
from tests.unit.test_memory_project import _svc


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def _repo(path: Path, branch: str = "main") -> Path:
    ws = seed_demo_workspace(path)
    _git(ws, "init", "-q", "-b", branch)
    _git(ws, "add", "-A")
    _git(ws, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    return ws


def _wait(client: TestClient, run_id: str, status: str) -> dict:
    for _ in range(200):
        detail = client.get(f"/runs/{run_id}").json()
        if detail["run"]["status"] == status:
            return detail
        time.sleep(0.05)
    raise AssertionError(f"{run_id} never reached {status}")


@pytest.mark.parametrize("branch", ["main", "master", "feature/coach"])
def test_runs_keep_current_branch_and_show_uncommitted_changes_before_signoff(tmp_path: Path, branch: str) -> None:
    svc = _svc(tmp_path)
    repo = _repo(tmp_path / "repo", branch=branch)
    head = _git(repo, "rev-parse", "HEAD")
    branches = _git(repo, "branch", "--list")
    (repo / "notes.md").write_text("my uncommitted work\n")
    original = (repo / "calc.py").read_text()
    project = svc.projects.create("p", "fix add", str(repo))
    with TestClient(create_app(svc)) as client:
        run = client.post("/runs", json={"goal": "fix add", "project_id": project.id, "runtime": "fake"}).json()
        assert Path(run["workspace"]) == repo.resolve()
        assert _git(repo, "branch", "--show-current") == branch
        _wait(client, run["id"], "DONE")
        # Visible in the user's working tree (and IDE) before any approval.
        assert (repo / "calc.py").read_text() != original
        assert (repo / "notes.md").read_text() == "my uncommitted work\n"
        assert client.get(f"/runs/{run['id']}").json()["pending_approval"] is None
        _wait(client, run["id"], "DONE")
        assert _git(repo, "rev-parse", "HEAD") == head
        assert _git(repo, "branch", "--list") == branches
        assert _git(repo, "diff", "--name-only") == "calc.py"
        assert _git(repo, "diff", "--cached", "--name-only") == ""
        assert _git(repo, "branch", "--show-current") == branch


def test_runs_stay_on_a_feature_branch(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    repo = _repo(tmp_path / "repo", branch="feature/coach")
    project = svc.projects.create("p", "fix add", str(repo))
    with TestClient(create_app(svc)) as client:
        run = client.post("/runs", json={"goal": "fix add", "project_id": project.id, "runtime": "fake"}).json()
        assert _git(repo, "branch", "--show-current") == "feature/coach"
        _wait(client, run["id"], "DONE")


async def test_direct_completion_survives_a_budget_pause_and_driver_restore(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    repo = _repo(tmp_path / "repo")
    driver = svc.driver(repo, "fake", "python")
    driver.recovery_options["complete_in_place"] = True
    run = await driver.run((await driver.create_async("fix add", budget_cents=0.01)).id)
    assert run.paused_reason == "budget_exceeded"
    restored = svc.restore_driver(run.id)
    assert restored.recovery_options["complete_in_place"] is True
    restored.decide(run.id, "approve", budget_unlimited=True)
    completed = await restored.run(run.id)
    assert completed.status == RunStatus.DONE
    assert svc.store.get_run(run.id).status == RunStatus.DONE
    assert svc.store.pending_approval(run.id) is None
