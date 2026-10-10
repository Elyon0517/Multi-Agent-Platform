
import pytest
from fastapi.testclient import TestClient

from agentlab.adapters.runtime.fake import FakeRuntime
from agentlab.api.app import create_app
from agentlab.core.memory.store import MemoryItem, MemoryKind
from agentlab.core.memory.summarizer import MemoryOp, MemoryOps, apply_ops
from agentlab.core.schemas import Event, Finding, Iteration, Run, RunStatus, Verdict
from tests.unit.test_memory_project import _svc


async def test_memory_ops_validate_ownership_and_protect_versions(tmp_path):
    svc = _svc(tmp_path)
    memory = svc.knowledge.memory
    items = [
        MemoryItem(project_id="p", namespace="project", kind=MemoryKind.NOTE, text="convention"),
        MemoryItem(project_id="p", namespace="project", kind=MemoryKind.NOTE, text="pinned", pinned=True),
        MemoryItem(project_id="p", namespace="project", kind=MemoryKind.DOCUMENT, text="document"),
        MemoryItem(project_id="other", namespace="project", kind=MemoryKind.NOTE, text="other"),
        MemoryItem(project_id="p", namespace="agent:coder", kind=MemoryKind.NOTE, text="coder"),
        MemoryItem(project_id="p", namespace="project", kind=MemoryKind.NOTE, text="not supplied"),
    ]
    await memory.add(items, embed=False)
    ops = MemoryOps(operations=[
        MemoryOp(action="update", target_id=items[0].id, text="new convention"),
        *[MemoryOp(action="retire", target_id=i.id) for i in items[1:]],
        MemoryOp(action="add", namespace="agent:unknown", text="invalid"),
        MemoryOp(action="update", namespace="global", target_id=items[4].id, text="invalid"),
        MemoryOp(action="add", namespace="global", text="Prefer concise replies"),
        MemoryOp(action="add", namespace="agent:coder", text="Check docstrings"),
    ])
    await apply_ops(memory, "p", "r", {"coder"}, items[:5], ops)
    assert items[0].valid_to and items[0].superseded_by
    assert all(i.valid_to is None for i in items[1:])
    assert [i.text for i in memory.items_in("project", "p")] == ["pinned", "document", "not supplied", "new convention"]
    assert memory.items_in("global")[0].project_id is None
    assert memory.items_in("global")[0].source == "summarizer"
    await apply_ops(memory, "p", "r2", {"coder"}, [], MemoryOps(operations=[
        MemoryOp(action="add", namespace="global", text="Prefer concise replies")]))
    assert len(memory.items_in("global")) == 1
    new = next(i for i in memory.items_in("project", "p") if i.text == "new convention")
    await apply_ops(memory, "p", "r3", {"coder"}, [new], MemoryOps(operations=[
        MemoryOp(action="retire", target_id=new.id)]))
    assert new.valid_to and not any(i.id == new.id for i in memory.items_in("project", "p"))


async def test_summarizer_feedback_resolution_dedup_and_usage(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    project = svc.projects.create("p", "goal", str(tmp_path))

    def summarize(inp):
        assert inp.diff is None and not inp.context.get("files")
        assert inp.context["findings"][0]["resolution"] == "absent_from_later_review"
        assert inp.context["findings"][0]["recurring"]
        existing = inp.context["existing_memory"]
        old = next((i for i in existing if i["namespace"] == "project"), None)
        return MemoryOps(operations=[
            MemoryOp(action="update" if old else "add", target_id=old["id"] if old else None,
                     text="Require clear public API docstrings"),
            MemoryOp(action="add", namespace="global", text="Prefer concise replies"),
        ])

    runtime = FakeRuntime({"summarizer": summarize})
    monkeypatch.setattr(type(svc), "runtime", lambda *a, **kw: runtime)
    for _ in range(2):
        run = Run(project_id=project.id, goal="goal", workspace=str(tmp_path), status=RunStatus.DONE)
        svc.store.create_run(run)
        svc.store.append_event(Event(run_id=run.id, type="approval.decided", actor="human",
                                     payload={"feedback": "Prefer concise replies"}))
        finding = Finding(severity="major", category="arch", file="x.py", issue="docstrings", confidence=1)
        for n in range(1, 4):
            svc.store.add_iteration(Iteration(run_id=run.id, n=n, phase=RunStatus.REVIEWING, diff_hash="x",
                                              verdicts=[Verdict(reviewer_id="arch-reviewer", verdict="APPROVE",
                                                                summary="", findings=[finding] if n < 3 else [])]))
        await svc.hooks.on_finished(run)
        await svc.hooks.on_finished(run)
        assert svc.store.get_run(run.id).cost_cents == 0
    assert len(runtime.inputs) == 2
    assert len(svc.knowledge.memory.items_in("project", project.id)) == 1
    assert len(svc.knowledge.memory.items_in("global")) == 1
    assert len(svc.store.usage_entries()) == 2
    assert svc.store.usage_by_role()[0]["role"] == "summarizer"
    assert sum(i.valid_to is not None for i in svc.knowledge.memory._items.values()) == 1


async def test_summarizer_failure_does_not_change_terminal_run(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    project = svc.projects.create("p", "goal", str(tmp_path))
    run = Run(project_id=project.id, goal="goal", workspace=str(tmp_path), status=RunStatus.CANCELLED)
    svc.store.create_run(run)
    def broken(*args, **kwargs):
        raise ConnectionError("offline")
    monkeypatch.setattr(type(svc), "runtime", broken)
    await svc.hooks.on_finished(run)
    assert svc.store.get_run(run.id).status == RunStatus.CANCELLED
    assert svc.store.records("summarization")[0]["status"] == "failed"


async def test_project_deletion_cleans_owned_data_preserves_shared(tmp_path):
    svc = _svc(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "code.py").write_text("keep")
    project = svc.projects.create("p", "goal", str(workspace))
    other = svc.projects.create("other", "goal", str(tmp_path))
    run = Run(project_id=project.id, goal="goal", workspace=str(workspace))
    svc.store.create_run(run)
    other_run = Run(project_id=other.id, goal="other", workspace=str(tmp_path), status=RunStatus.DONE)
    svc.store.create_run(other_run)
    for pid, ns in [(None, "global"), (project.id, "project"), (project.id, "agent:coder"), (other.id, "project")]:
        await svc.knowledge.note(pid, ns, "keep global and other only")
    svc.store.put_record("thread", "t", {"id": "t", "project_id": project.id})
    svc.store.put_record("root_turn", "turn", {"project_id": project.id})
    from agentlab.core.monitor import UsageRecorder
    from agentlab.core.schemas import Artifact, Usage
    UsageRecorder(svc.store, "run", run.id, project.id)(Usage(tokens_in=12).for_call("coder", "fake", "fake"))
    owned, sha = svc.blobs.put("owned")
    shared, shared_sha = svc.blobs.put("shared")
    for target, ref, digest in [(run, owned, sha), (run, shared, shared_sha), (other_run, shared, shared_sha)]:
        svc.store.add_artifact(Artifact(run_id=target.id, kind="plan", content_ref=ref, sha256=digest))
    snapshot = tmp_path / "snapshots" / "test"
    snapshot.mkdir(parents=True)
    (snapshot / "object").write_text("delete")
    svc.store.save_checkpoint(run.id, {"workspace": {"snapshot_dir": str(snapshot)}})
    subscription = svc.bus.subscribe(run.id)
    with TestClient(create_app(svc)) as client:
        assert client.delete(f"/projects/{project.id}").status_code == 409
        assert snapshot.exists()
        run.status = RunStatus.CANCELLED
        svc.store.save_run(run)
        assert client.delete(f"/projects/{project.id}").status_code == 200
        assert client.delete(f"/projects/{project.id}").status_code == 404
        assert client.get(f"/runs/{run.id}").status_code == 404
    assert (workspace / "code.py").read_text() == "keep"
    assert not snapshot.exists()
    assert svc.blobs.get(shared) == "shared"
    with pytest.raises(FileNotFoundError):
        svc.blobs.get(owned)
    assert svc.projects.get(other.id)
    assert len(svc.knowledge.memory.items_in("global")) == 1
    assert len(svc.knowledge.memory.items_in("project", other.id)) == 1
    assert not svc.knowledge.memory.items_in("project", project.id)
    assert not svc.knowledge.memory.items_in("agent:coder", project.id)
    assert not svc.store.records("thread") and not svc.store.records("root_turn")
    assert svc.store.usage_entries()[0]["project_id"] == project.id
    assert run.id not in svc.bus._subs
    with pytest.raises(StopAsyncIteration):
        await anext(subscription)


async def test_summarizer_cache_rolls_back_if_commit_fails(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    project = svc.projects.create("p", "goal", str(tmp_path))
    run = Run(project_id=project.id, goal="goal", workspace=str(tmp_path), status=RunStatus.DONE)
    svc.store.create_run(run)
    runtime = FakeRuntime({"summarizer": lambda inp: MemoryOps(operations=[MemoryOp(action="add", text="lesson")])})
    monkeypatch.setattr(type(svc), "runtime", lambda *a, **kw: runtime)
    original = svc.store.put_record
    def fail_completion(kind, key, data):
        if kind == "summarization" and data.get("status") == "completed":
            raise RuntimeError("commit failed")
        original(kind, key, data)
    monkeypatch.setattr(svc.store, "put_record", fail_completion)
    await svc.hooks.on_finished(run)
    assert not svc.knowledge.memory.items_in("project", project.id)
    assert len(svc.store.usage_entries()) == 1
    assert svc.store.records("summarization")[0]["status"] == "failed"


async def test_event_forget_closes_and_removes_subscriptions():
    from agentlab.adapters.events import InProcessEventBus
    bus = InProcessEventBus()
    subscription = bus.subscribe("deleted")
    bus.forget("deleted")
    with pytest.raises(StopAsyncIteration):
        await anext(subscription)
    await subscription.aclose()
    assert "deleted" not in bus._subs


def test_interrupted_summarizer_calls_recover_usage_once(tmp_path):
    from agentlab.core.monitor import recover_interrupted_calls
    svc = _svc(tmp_path)
    svc.store.put_record("summarizer_call", "call", {
        "id": "call", "run_id": "r", "project_id": "p", "status": "in_flight", "role": "summarizer",
        "usage": {"tokens_in": 10, "tokens_out": 2, "cost_cents": 0.1}})
    recover_interrupted_calls(svc.store)
    recover_interrupted_calls(svc.store)
    assert len(svc.store.usage_entries()) == 1
    row = svc.store.usage_entries()[0]
    assert row["source"] == "summarization" and row["role"] == "summarizer" and row["tokens_in"] == 10
