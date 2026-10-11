import subprocess
import time
from pathlib import Path

from fastapi.testclient import TestClient

from agentlab.api.app import create_app
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


def test_runs_edit_the_repository_on_their_own_branch_and_show_changes_before_signoff(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    repo = _repo(tmp_path / "repo")
    (repo / "notes.md").write_text("my uncommitted work\n")
    original = (repo / "calc.py").read_text()
    project = svc.projects.create("p", "fix add", str(repo))
    with TestClient(create_app(svc)) as client:
        run = client.post("/runs", json={"goal": "fix add", "project_id": project.id, "runtime": "fake"}).json()
        assert Path(run["workspace"]) == repo.resolve()
        assert _git(repo, "branch", "--show-current") == f"agentlab/{run['id']}"
        _wait(client, run["id"], "WAITING_HUMAN")
        # Visible in the user's working tree (and IDE) before any approval.
        assert (repo / "calc.py").read_text() != original
        assert (repo / "notes.md").read_text() == "my uncommitted work\n"
        assert client.post(f"/runs/{run['id']}/decision", json={"decision": "approve"}).status_code == 200
        _wait(client, run["id"], "DONE")
        assert _git(repo, "branch", "--show-current") == f"agentlab/{run['id']}"  # the branch is the user's now


def test_runs_stay_on_a_feature_branch(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    repo = _repo(tmp_path / "repo", branch="feature/coach")
    project = svc.projects.create("p", "fix add", str(repo))
    with TestClient(create_app(svc)) as client:
        run = client.post("/runs", json={"goal": "fix add", "project_id": project.id, "runtime": "fake"}).json()
        assert _git(repo, "branch", "--show-current") == "feature/coach"
        _wait(client, run["id"], "WAITING_HUMAN")
