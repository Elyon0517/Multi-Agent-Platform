import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentlab.api.app import create_app
from agentlab.core.project_config import ProjectSettings
from agentlab.demo import seed_demo_workspace
from tests.unit.test_memory_project import _svc


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def _repo(path: Path) -> Path:
    ws = seed_demo_workspace(path)
    _git(ws, "init", "-q")
    _git(ws, "add", "-A")
    _git(ws, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    return ws


def _worktree_project(svc, repo: Path):
    project = svc.projects.create("p", "fix add", str(repo))
    project.settings = ProjectSettings(workspace_mode="worktree")
    svc.projects.save(project)
    return project


def _wait(client: TestClient, run_id: str, status: str) -> dict:
    for _ in range(200):
        detail = client.get(f"/runs/{run_id}").json()
        if detail["run"]["status"] == status:
            return detail
        time.sleep(0.05)
    raise AssertionError(f"{run_id} never reached {status}")


def test_parallel_runs_carry_uncommitted_work_and_apply_back_on_signoff(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    repo = _repo(tmp_path / "repo")
    (repo / "notes.md").write_text("draft\n")  # uncommitted user work the agents must see
    original = (repo / "calc.py").read_text()
    project = _worktree_project(svc, repo)
    with TestClient(create_app(svc)) as client:
        first = client.post("/runs", json={"goal": "fix add", "project_id": project.id, "runtime": "fake"}).json()
        second = client.post("/runs", json={"goal": "again", "project_id": project.id, "runtime": "fake"})
        assert second.status_code == 200
        worktree = Path(first["workspace"])
        assert worktree != repo.resolve() and (worktree / "notes.md").read_text() == "draft\n"

        detail = _wait(client, first["id"], "WAITING_HUMAN")
        assert detail["pending_approval"]["reason"] == "signoff"
        assert (repo / "calc.py").read_text() == original  # untouched until approval
        assert client.post(f"/runs/{first['id']}/decision", json={"decision": "approve"}).status_code == 200
        _wait(client, first["id"], "DONE")
        assert "a + b" in (repo / "calc.py").read_text()
        assert (repo / "notes.md").read_text() == "draft\n"
        assert _git(repo, "diff", "--name-only", "HEAD").split() == ["calc.py"]  # applied, not committed

        branch = f"agentlab/{first['id']}"
        for _ in range(100):  # cleanup runs after the run finishes: directory first, then the branch
            if not worktree.exists() and branch not in _git(repo, "branch", "--list"):
                break
            time.sleep(0.05)
        assert not worktree.exists()
        assert branch not in _git(repo, "branch", "--list")


def test_conflict_keeps_signoff_pending_and_aborting_discards_the_worktree(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    repo = _repo(tmp_path / "repo")
    project = _worktree_project(svc, repo)
    with TestClient(create_app(svc)) as client:
        run = client.post("/runs", json={"goal": "fix add", "project_id": project.id, "runtime": "fake"}).json()
        _wait(client, run["id"], "WAITING_HUMAN")
        (repo / "calc.py").write_text("def add(a, b):\n    return b - a\n")  # the user edited the same lines
        response = client.post(f"/runs/{run['id']}/decision", json={"decision": "approve"})
        assert response.status_code == 409 and f"agentlab/{run['id']}" in response.text
        assert (repo / "calc.py").read_text() == "def add(a, b):\n    return b - a\n"
        assert client.get(f"/runs/{run['id']}").json()["pending_approval"]["reason"] == "signoff"

        assert client.post(f"/runs/{run['id']}/decision", json={"decision": "abort"}).status_code == 200
        _wait(client, run["id"], "CANCELLED")
        for _ in range(100):
            if not Path(run["workspace"]).exists():
                break
            time.sleep(0.05)
        assert not Path(run["workspace"]).exists()
        assert (repo / "calc.py").read_text() == "def add(a, b):\n    return b - a\n"


@pytest.mark.parametrize("during_commit", [False, True])
def test_changed_worktree_cannot_integrate_under_old_signoff(tmp_path: Path, monkeypatch, during_commit) -> None:
    svc = _svc(tmp_path)
    repo = _repo(tmp_path / "repo")
    original = (repo / "calc.py").read_text()
    project = _worktree_project(svc, repo)
    with TestClient(create_app(svc)) as client:
        run = client.post("/runs", json={"goal": "fix add", "project_id": project.id, "runtime": "fake"}).json()
        _wait(client, run["id"], "WAITING_HUMAN")
        source = Path(run["workspace"]) / "calc.py"
        if during_commit:
            from agentlab.adapters import worktree

            original_commit = worktree._commit

            def changed_commit(path, message):
                source.write_text(source.read_text() + "# changed during delivery commit\n")
                return original_commit(path, message)

            monkeypatch.setattr(worktree, "_commit", changed_commit)
            response = client.post(f"/runs/{run['id']}/decision", json={"decision": "approve"})
            assert response.status_code == 409
            assert (repo / "calc.py").read_text() == original
            monkeypatch.setattr(worktree, "_commit", original_commit)
        else:
            source.write_text(source.read_text() + "# changed after review\n")
        response = client.post(f"/runs/{run['id']}/decision", json={"decision": "approve"})
        assert response.status_code == 200
        assert response.json()["status"] == "WAITING_HUMAN"
        detail = client.get(f"/runs/{run['id']}").json()
        assert detail["pending_approval"]["reason"] == "workspace_changed"
        assert (repo / "calc.py").read_text() == original
        assert source.exists()
        assert client.post(f"/runs/{run['id']}/decision", json={"decision": "abort"}).status_code == 200
        _wait(client, run["id"], "CANCELLED")
        for _ in range(100):
            if not Path(run["workspace"]).exists():
                break
            time.sleep(0.05)
        assert not Path(run["workspace"]).exists()
        assert (repo / "calc.py").read_text() == original
