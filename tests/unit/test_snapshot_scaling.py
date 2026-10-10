from __future__ import annotations

import subprocess

import pytest

from agentlab.adapters.workspace import GitWorkspace
from agentlab.core.ports import WorkspaceUnreadable
from agentlab.core.schemas import FileEdit
from tests.unit.test_driver import make_driver


def git(root, *args):  # type: ignore[no-untyped-def]
    return subprocess.check_output(["git", "-C", str(root), *args]).decode().strip()


def commit(root):  # type: ignore[no-untyped-def]
    git(root, "add", "-A")
    git(root, "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "--allow-empty", "-qm", "test")
    return git(root, "rev-parse", "HEAD")


@pytest.mark.parametrize("tracked", [False, True], ids=["embedded", "gitlink"])
async def test_nested_repository_head_changes_without_modifying_parent_objects_or_index(tmp_path, tracked):  # type: ignore[no-untyped-def]
    ws = GitWorkspace(tmp_path)
    await ws.ensure_repo()
    child = tmp_path / "vendor"
    child.mkdir()
    git(child, "init", "-q")
    (child / "code.py").write_text("a = 1\n")
    old = commit(child)
    if tracked:
        git(tmp_path, "update-index", "--add", "--cacheinfo", f"160000,{old},vendor")
    before = {p.relative_to(tmp_path / ".git") for p in (tmp_path / ".git/objects").rglob("*")}
    index = (tmp_path / ".git/index").read_bytes()
    ws.begin_run()
    assert ws._baseline_meta["vendor"] == (old, "submodule")
    (child / "code.py").write_text("a = 2\n")
    new = commit(child)
    diff = await ws.diff()
    assert "submodule" in diff and old in diff and new in diff
    assert (tmp_path / ".git/index").read_bytes() == index
    assert {p.relative_to(tmp_path / ".git") for p in (tmp_path / ".git/objects").rglob("*")} == before
    objects = ws._snapshot_dir.name
    ws.close()
    from pathlib import Path
    assert not Path(objects).exists()


async def test_uninitialized_gitlink_uses_index_commit_not_parent_head(tmp_path):  # type: ignore[no-untyped-def]
    ws = GitWorkspace(tmp_path)
    await ws.ensure_repo()
    oid = "1" * 40
    git(tmp_path, "update-index", "--add", "--cacheinfo", f"160000,{oid},vendor")
    (tmp_path / "vendor").mkdir()
    ws.begin_run()
    assert ws._baseline_meta["vendor"] == (oid, "submodule")
    assert await ws.diff() == ""


async def test_unborn_embedded_repository_and_dirty_edits_are_visible(tmp_path):  # type: ignore[no-untyped-def]
    ws = GitWorkspace(tmp_path)
    await ws.ensure_repo()
    child = tmp_path / "vendor"
    child.mkdir()
    git(child, "init", "-q")
    ws.begin_run()
    ws.apply_edits([FileEdit(path="vendor/code.py", content="unborn change\n")])
    assert "embedded-unborn -> embedded-unborn" in await ws.diff()
    commit(child)
    assert "embedded-unborn -> submodule" in await ws.diff()
    ws.begin_run()
    ws.apply_edits([FileEdit(path="vendor/code.py", content="actual change\n")])
    assert "submodule-dirty" in await ws.diff()


async def test_2000_files_use_one_hash_process_per_snapshot_and_no_parent_objects(tmp_path):  # type: ignore[no-untyped-def]
    ws = GitWorkspace(tmp_path)
    await ws.ensure_repo()
    for n in range(2000):
        (tmp_path / f"file{n}.py").write_text(f"value = {n}\n")
    before = set((tmp_path / ".git/objects").rglob("*"))
    commands = []
    original = ws._git_bytes
    def counted(*args, **kwargs):  # type: ignore[no-untyped-def]
        commands.append(args)
        return original(*args, **kwargs)
    ws._git_bytes = counted
    ws.begin_run()
    ws.apply_edits([FileEdit(path="file0.py", content="value = 42\n")])
    assert "+value = 42" in await ws.diff()
    assert len([c for c in commands if c[0] == "hash-object"]) == 2
    assert len(commands) < 20
    assert set((tmp_path / ".git/objects").rglob("*")) == before


async def test_unreadable_during_run_has_its_own_approval_reason(cfg, tmp_path):  # type: ignore[no-untyped-def]
    driver = await make_driver(cfg, tmp_path)
    run = driver.create("g")
    async def unreadable(_):  # type: ignore[no-untyped-def]
        raise WorkspaceUnreadable("do not expose this message")
    driver._handlers[run.status] = unreadable
    await driver.run(run.id)
    approval = driver.store.pending_approval(run.id)
    assert approval.reason == "workspace_unreadable"
    assert "do not expose" not in str(approval.payload)


async def test_api_unreadable_baseline_returns_explicit_error_not_500(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from agentlab.api.app import create_app
    from agentlab.bootstrap import build_services
    from agentlab.settings import Settings
    from tests.conftest import CONFIG_DIR
    svc = build_services(Settings(config_dir=CONFIG_DIR, data_dir=tmp_path, _env_file=None))
    def unreadable(self):  # type: ignore[no-untyped-def]
        raise WorkspaceUnreadable("private detail")
    monkeypatch.setattr(GitWorkspace, "begin_run", unreadable)
    with TestClient(create_app(svc)) as client:
        response = client.post("/runs", json={"goal": "g", "runtime": "fake"})
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "workspace_unreadable"
    assert "private detail" not in response.text


@pytest.mark.parametrize("replacement", [False, True], ids=["deleted", "replaced-by-file"])
async def test_initialized_gitlink_removal_or_replacement_is_visible(tmp_path, replacement):  # type: ignore[no-untyped-def]
    import shutil
    ws = GitWorkspace(tmp_path)
    await ws.ensure_repo()
    child = tmp_path / "vendor"
    child.mkdir()
    git(child, "init", "-q")
    oid = commit(child)
    git(tmp_path, "update-index", "--add", "--cacheinfo", f"160000,{oid},vendor")
    ws.begin_run()
    shutil.rmtree(child)
    if replacement:
        child.write_text("replacement source\n")
    diff = await ws.diff()
    assert "vendor" in diff
    assert "submodule -> text" in diff
    if replacement:
        assert "replacement source" in diff
    else:
        assert "new blob absent" in diff
