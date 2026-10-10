from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import pytest

from agentlab.adapters.store.memory import InMemoryStore
from agentlab.core.ports import RunBusy, WorkspaceRootRequired
from agentlab.core.schemas import Approval, Artifact, Event, Iteration, Run, RunStatus, Step


@pytest.fixture
def database_url():
    admin = os.environ.get("AGENTLAB_TEST_DATABASE_URL")
    if not admin:
        pytest.skip("set AGENTLAB_TEST_DATABASE_URL to a disposable local PostgreSQL database")
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql

    from agentlab.db.migrate import upgrade

    schema = "p2_test_" + uuid4().hex
    dsn = admin.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    url = dsn + ("&" if "?" in dsn else "?") + "options=" + quote(f"-csearch_path={schema},public")
    try:
        upgrade(url)
        upgrade(url)  # existing bootstrap SQL and repeated upgrades are safe
        yield url
    finally:
        with psycopg.connect(dsn, autocommit=True) as c:
            names = c.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname LIKE %s", (schema[:20] + "_%",)
            ).fetchall()
            for (name,) in names:
                c.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))
            c.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    if request.param == "memory":
        return InMemoryStore()
    from agentlab.adapters.store.postgres import PostgresStore

    return PostgresStore(request.getfixturevalue("database_url"))


def test_store_contract(store):
    r = Run(goal="goal", workspace="/tmp/test")
    store.create_run(r)
    it = Iteration(run_id=r.id, n=1, phase=RunStatus.GATING, diff_hash="abc")
    store.add_iteration(it)
    store.add_step(Step(run_id=r.id, iteration_n=1, role="coder", model_alias="fake", model="fake"))
    store.add_artifact(Artifact(run_id=r.id, kind="plan", content_ref="blob://test", sha256="abc"))
    approval = Approval(run_id=r.id, reason="budget_exceeded", on_approve=RunStatus.PLANNING)
    store.create_approval(approval)
    store.save_checkpoint(r.id, {"inputs": ["frozen"]})
    store.put_record("planning", "test", {"cost": 5})
    event = store.append_event(Event(run_id=r.id, type="run.created", actor="driver"))
    assert event.seq == 1
    assert store.append_event(Event(run_id=r.id, type="run.status", actor="driver")).seq == 2
    assert [e.seq for e in store.events(r.id, 1)] == [2]
    assert store.get_run(r.id) == r
    assert store.iterations(r.id) == [it]
    assert len(store.steps(r.id)) == len(store.artifacts(r.id)) == 1
    assert store.pending_approval(r.id) == approval
    assert store.checkpoint(r.id) == {"inputs": ["frozen"]}
    assert store.records("planning") == [{"cost": 5}]
    with pytest.raises(RuntimeError), store.transaction():
        r.cost_cents = 90
        store.save_run(r)
        store.put_record("planning", "test", {"cost": 90})
        raise RuntimeError("rollback")
    assert store.get_run(r.id).cost_cents == 0
    assert store.records("planning") == [{"cost": 5}]
    with store.lock_run(r.id), pytest.raises(RunBusy), store.lock_run(r.id):
        pass


def services(database_url, tmp_path):
    from agentlab.bootstrap import build_services
    from agentlab.settings import Settings

    return build_services(
        Settings(
            _env_file=None,
            database_url=database_url,
            runtime="fake",
            sandbox="local",
            data_dir=tmp_path / "data",
            env_file=tmp_path / "absent.env",
        )
    )


async def driver_for(database_url, tmp_path):
    from agentlab.core.loop.hooks import NoHooks
    from agentlab.demo import seed_demo_workspace

    svc = services(database_url, tmp_path)
    d = svc.driver(seed_demo_workspace(tmp_path / "ws"), "fake")
    d.hooks = NoHooks()
    await d.workspace.ensure_repo()
    return svc, d


async def test_signoff_survives_restart(database_url, tmp_path):
    svc, d = await driver_for(database_url, tmp_path)
    r = await d.run(d.create("fix add").id)
    assert r.paused_reason == "signoff"
    diff = await d.workspace.diff()
    before_steps = len(svc.store.steps(r.id))
    svc2 = services(database_url, tmp_path)
    restored = svc2.restore_driver(r.id)
    assert await restored.workspace.diff() == diff
    assert (await restored.run(r.id)).status == RunStatus.WAITING_HUMAN
    assert len(svc2.store.steps(r.id)) == before_steps
    assert all(s.prompt_ref and s.response_ref for s in svc2.store.steps(r.id))
    restored.decide(r.id, "approve")
    assert (await restored.run(r.id)).status == RunStatus.DONE
    assert not Path(svc2.store.checkpoint(r.id)["workspace"]["snapshot_dir"]).exists()


async def test_budget_and_abort_survive_restart(database_url, tmp_path):
    svc, d = await driver_for(database_url, tmp_path)
    r = await d.run(d.create("fix add", budget_cents=0.01).id)
    assert r.paused_reason == "budget_exceeded"
    restored = services(database_url, tmp_path).restore_driver(r.id)
    required = svc.store.pending_approval(r.id).payload["required_budget_cents"]
    with pytest.raises(ValueError):
        restored.decide(r.id, "approve")
    restored.decide(r.id, "approve", budget_cents=max(500, required))
    r = await restored.run(r.id)
    assert r.paused_reason == "signoff"
    again = services(database_url, tmp_path).restore_driver(r.id)
    again.decide(r.id, "abort")
    assert (await again.run(r.id)).status == RunStatus.CANCELLED
    assert not svc.store.checkpoint(r.id)["inputs"]
    assert not svc.store.checkpoint(r.id)["results"]


async def test_partial_review_cache_is_durable(database_url, tmp_path):
    from agentlab.core.llm.retry import ParallelFailure

    svc, d = await driver_for(database_url, tmp_path)
    r = d.create("fix add")
    await d._planning(r)
    await d._coding(r)
    await d._gating(r)
    # demo first coder intentionally fails the gate; its second edit passes.
    if r.status == RunStatus.CODING:
        await d._coding(r)
        await d._gating(r)
    assert r.status == RunStatus.REVIEWING
    original = d.runtime
    first = d.cfg.reviewer_roles[0]

    class Partial:
        async def run_parallel(self, inputs, out, ctx):
            result = await original.run_agent(first, inputs[first], out, ctx)
            ctx.on_result(result)
            raise ParallelFailure(RuntimeError("remaining reviewer failed"), [result])

    d.runtime = Partial()
    r = await d.run(r.id)
    assert r.paused_reason == "execution_error"
    paid = r.cost_cents
    frozen = svc.store.checkpoint(r.id)["inputs"]
    # Memory can change while paused without invalidating the frozen inputs.
    await svc.knowledge.note(None, "global", "new context while paused")
    svc2 = services(database_url, tmp_path)
    restored = svc2.restore_driver(r.id)
    assert svc2.store.checkpoint(r.id)["inputs"] == frozen
    restored.decide(r.id, "approve")
    r = svc2.store.get_run(r.id)
    await restored._reviewing(r)
    assert r.status == RunStatus.ARBITRATING
    assert first not in [role for role, _ in restored.runtime.calls]
    assert len([s for s in svc2.store.steps(r.id) if s.role in d.cfg.reviewer_roles]) == 3
    assert r.cost_cents == pytest.approx(paid + 0.2)
    assert not svc2.store.checkpoint(r.id)["results"]


async def test_unknown_inflight_requires_explicit_decision(database_url, tmp_path):
    svc, d = await driver_for(database_url, tmp_path)
    r = d.create("fix add")
    svc.store.put_record("attempt", "unfinished", {"id": "unfinished", "run_id": r.id, "status": "in_flight"})
    restored = services(database_url, tmp_path).restore_driver(r.id)
    r = await restored.run(r.id)
    assert r.paused_reason == "interrupted_call"
    assert not restored.runtime.calls
    restored.decide(r.id, "approve")
    assert (
        next(a for a in svc.store.records("attempt") if a["id"] == "unfinished")["status"] == "unknown_authorized_retry"
    )
    assert (await restored.run(r.id)).paused_reason == "signoff"


async def test_memory_projects_and_planning_persist(database_url, tmp_path):
    from agentlab.adapters.runtime.fake import FakeRuntime
    from agentlab.core.memory.store import GLOBAL
    from agentlab.core.project import ProjectPlan

    svc = services(database_url, tmp_path)
    await svc.knowledge.ingest("guide.txt", b"old guide")
    await svc.knowledge.ingest("guide.txt", b"new guide")
    project = svc.projects.create("demo", "fix add", str(tmp_path / "ws"), publish=False)
    from agentlab.core.project import PhasePlan

    runtime = FakeRuntime({"project-planner": lambda _: ProjectPlan(phases=[PhasePlan(title="Build", steps=["Fix"])])})
    await svc.projects.plan(project, runtime, svc.knowledge, 500)
    svc.projects.link_run(project.id, project.phases[0].steps[0].id, "example")
    svc2 = services(database_url, tmp_path)
    assert svc2.projects.get(project.id).phases[0].steps[0].run_ids == ["example"]
    assert svc2.projects.planning_attempts[0]["cost_cents"] == 0.1
    assert [i.text for i in svc2.knowledge.memory.items_in(GLOBAL)] == ["new guide"]
    assert len(svc2.store.records("memory")) == 2
    svc2.knowledge.delete("guide.txt")
    assert not services(database_url, tmp_path).knowledge.documents()


def test_kill9_recovers_paid_plan(database_url, tmp_path):
    worker = r"""
import asyncio, json, os, time
from pathlib import Path
from agentlab.bootstrap import build_services
from agentlab.settings import Settings
from agentlab.demo import seed_demo_workspace
from agentlab.core.schemas import Plan
from agentlab.core.loop.hooks import NoHooks
root=Path(os.environ['P2_TEST_ROOT'])
s=Settings(_env_file=None,database_url=os.environ['P2_TEST_DSN'],data_dir=root/'data',runtime='fake',sandbox='local',env_file=root/'absent.env')
svc=build_services(s);d=svc.driver(seed_demo_workspace(root/'ws'),'fake');d.hooks=NoHooks()
async def go():
 await d.workspace.ensure_repo()
 r=d.create('fix add')
 await d._agent(r,'planner',d._input(r),Plan)
 (root/'ready.json').write_text(json.dumps({'id':r.id,'cost':r.cost_cents,'tree':svc.store.checkpoint(r.id)['workspace']['baseline_tree']}))
 while True: await asyncio.sleep(1)
asyncio.run(go())
"""
    process = subprocess.Popen(
        [sys.executable, "-c", worker],
        env={**os.environ, "P2_TEST_ROOT": str(tmp_path), "P2_TEST_DSN": database_url},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 30
        while not (tmp_path / "ready.json").exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (tmp_path / "ready.json").exists(), process.communicate(timeout=2)
        saved = json.loads((tmp_path / "ready.json").read_text())
        os.kill(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
        svc = services(database_url, tmp_path)
        d = svc.restore_driver(saved["id"])
        assert svc.store.checkpoint(saved["id"])["workspace"]["baseline_tree"] == saved["tree"]
        r = asyncio.run(d.run(saved["id"]))
        assert r.paused_reason == "signoff"
        assert "planner" not in [role for role, _ in d.runtime.calls]
        assert len([s for s in svc.store.steps(r.id) if s.role == "planner"]) == 1
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


async def test_monorepo_subdirectory_does_not_init_repo(tmp_path):
    from agentlab.adapters.workspace import GitWorkspace

    root = GitWorkspace(tmp_path)
    await root.ensure_repo()
    child = tmp_path / "package"
    child.mkdir()
    ws = GitWorkspace(child)
    with pytest.raises(WorkspaceRootRequired):
        await ws.ensure_repo()
    assert not (child / ".git").exists()


async def test_paid_response_recovers_before_result_checkpoint(database_url, tmp_path):
    from agentlab.core.llm.structured import Completion, StructuredCaller
    from agentlab.core.schemas import Plan, Usage

    svc, d = await driver_for(database_url, tmp_path)
    r = d.create("fix add")

    class CallerRuntime:
        async def run_agent(self, role, inp, out, ctx):
            # Simulate death after durable response/usage, before AgentResult callback.
            from dataclasses import replace

            def crash(_):
                raise RuntimeError("crash after validation")

            async def chat(**kwargs):
                return Completion(
                    Plan(summary="paid plan", steps=["fix"], acceptance_criteria=["pass"]).model_dump_json(),
                    2_000_000,
                    50,
                )

            return await StructuredCaller(d.cfg, chat).call(role, inp, out, replace(ctx, on_result=crash))

    d.runtime = CallerRuntime()
    r = await d.run(r.id)
    assert r.paused_reason == "execution_error"
    attempts = [a for a in svc.store.records("attempt") if a["run_id"] == r.id]
    assert len(attempts) == 1 and attempts[0]["status"] == "completed"
    assert r.tokens_in == 2_000_000 and r.tokens_out == 50
    cost = r.cost_cents
    assert cost > r.budget_cents
    restored = services(database_url, tmp_path).restore_driver(r.id)
    restored.decide(r.id, "approve")
    r = svc.store.get_run(r.id)
    await restored._planning(r)
    assert not restored.runtime.calls
    assert r.cost_cents == cost
    steps = svc.store.steps(r.id)
    assert len(steps) == 1 and steps[0].usage == Usage(tokens_in=2_000_000, tokens_out=50, cost_cents=cost)
    assert svc.blobs.get(steps[0].response_ref).startswith('{"summary":"paid plan"')


async def test_planning_failure_usage_is_durable(database_url, tmp_path):
    from agentlab.core.llm.structured import Completion, StructuredCaller
    from agentlab.core.project import ProjectPlan

    svc = services(database_url, tmp_path)
    project = svc.projects.create("failed", "goal", str(tmp_path / "ws"), publish=False)

    class Broken:
        async def run_agent(self, role, inp, out, ctx):
            async def chat(**kwargs):
                return Completion("not json", 100, 50)

            return await StructuredCaller(svc.cfg, chat).call(role, inp, ProjectPlan, ctx)

    from agentlab.core.llm.retry import LlmError

    with pytest.raises(LlmError):
        await svc.projects.plan(project, Broken(), svc.knowledge, 500)
    svc2 = services(database_url, tmp_path)
    assert not svc2.projects.list()
    ledger = svc2.projects.planning_attempts[0]
    assert ledger["status"] == "failed" and ledger["tokens_in"] == 300
    assert len(svc2.store.records("planning_call")) == 3
    assert all(a["status"] == "completed" for a in svc2.store.records("planning_call"))


async def test_other_process_memory_changes_are_not_overwritten(database_url, tmp_path):
    svc = services(database_url, tmp_path)
    await svc.knowledge.ingest("shared.txt", b"original")
    other = services(database_url, tmp_path)
    await other.knowledge.ingest("shared.txt", b"updated")
    await svc.knowledge.note(None, "global", "unrelated note")
    assert [i.text for i in svc.knowledge.memory.items_in("global") if i.source == "shared.txt"] == ["updated"]
    assert len(svc.store.records("memory")) == 3


async def test_api_decides_persisted_approval_after_restart(database_url, tmp_path):
    from fastapi.testclient import TestClient

    from agentlab.api.app import create_app

    _svc, d = await driver_for(database_url, tmp_path)
    r = await d.run(d.create("fix add").id)
    svc2 = services(database_url, tmp_path)
    with TestClient(create_app(svc2)) as client:
        assert client.post(f"/runs/{r.id}/resume").json()["status"] == "WAITING_HUMAN"
        assert client.get(f"/runs/{r.id}").json()["pending_approval"]["reason"] == "signoff"
        result = client.post(f"/runs/{r.id}/decision", json={"decision": "approve"})
        assert result.status_code == 200 and result.json()["status"] == "DONE"


async def test_reject_clears_durable_paid_result_cache(database_url, tmp_path):
    from agentlab.core.schemas import Plan

    svc, d = await driver_for(database_url, tmp_path)
    r = d.create("fix add")
    await d._agent(r, "planner", d._input(r), Plan)
    d._escalate(r, "execution_error", {}, on_approve=r.status)
    assert svc.store.checkpoint(r.id)["results"]
    restored = services(database_url, tmp_path).restore_driver(r.id)
    restored.decide(r.id, "reject", "Try a new plan")
    assert not svc.store.checkpoint(r.id)["results"]
    assert not svc.store.checkpoint(r.id)["inputs"]
    assert svc.store.get_run(r.id).status == RunStatus.PLANNING


async def test_baseline_objects_are_owned_not_only_git_alternates(tmp_path):
    from agentlab.adapters.workspace import GitWorkspace

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "file.py").write_text("original = 1\n")
    ws = GitWorkspace(workspace, snapshot_dir=tmp_path / "snapshots")
    await ws.ensure_repo()
    subprocess.run(["git", "-C", str(workspace), "add", "file.py"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(workspace), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "commit", "-m", "baseline"], check=True, capture_output=True)
    original = subprocess.check_output(["git", "-C", str(workspace), "rev-parse", "HEAD:file.py"]).decode().strip()
    ws.begin_run()
    state = ws.export_state()
    tree = state["baseline_tree"]
    objects = tmp_path / "snapshots" / "objects"
    assert (objects / original[:2] / original[2:]).exists()
    assert (objects / tree[:2] / tree[2:]).exists()


async def test_project_dispatch_and_conversation_survive_postgres_restart(database_url, tmp_path):
    from agentlab.bootstrap import build_services
    from agentlab.core.conversation import Conversation, Message
    from agentlab.core.project_config import ProjectSettings
    from agentlab.demo import seed_demo_workspace
    from agentlab.settings import Settings
    from tests.conftest import CONFIG_DIR

    settings = Settings(
        store_backend="postgres",
        database_url=database_url,
        runtime="fake",
        config_dir=CONFIG_DIR,
        data_dir=tmp_path / "data",
        env_file=tmp_path / ".env",
        _env_file=None,
    )
    svc = build_services(settings)
    workspace = seed_demo_workspace(tmp_path / "workspace")
    project = svc.projects.create("persistent", "fix add", str(workspace))
    project.settings = ProjectSettings()
    svc.projects.save(project)
    conversation = Conversation(project_id=project.id, title="Discussion")
    svc.store.put_record("thread", conversation.id, conversation.model_dump(mode="json"))
    driver = svc.driver(workspace, "fake", "python", project.id)
    await driver.workspace.ensure_repo()

    def record(run):
        conversation.messages.append(Message(author="user", text=run.goal, run_id=run.id))
        svc.store.put_record("thread", conversation.id, conversation.model_dump(mode="json"))

    run = await driver.create_async("fix add", project_id=project.id, thread_id=conversation.id, on_create=record)
    await driver._planning(run)
    other = build_services(settings)
    restored = other.restore_driver(run.id)
    assert other.store.get_run(run.id).thread_id == conversation.id
    assert other.projects.get(project.id).settings.mode == "auto"
    assert other.store.records("thread")[0]["messages"][0]["run_id"] == run.id
    assert restored.recovery_options["assignments"] == driver.recovery_options["assignments"]
    assert len(other.store.artifacts(run.id, "dispatch")) == 1
    driver.workspace.close()


def test_existing_projects_migrate_and_backup_is_readonly(database_url, monkeypatch):
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row

    from agentlab.adapters.store.postgres import PostgresStore
    from agentlab.db.isolation import migrate, schema_name

    with psycopg.connect(database_url, row_factory=dict_row) as c:
        base = c.execute("SELECT current_schema() AS name").fetchone()["name"]
        archive = base[:20] + "_legacy"
        c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(archive)))
        c.execute("DROP TABLE run_directory; DROP TABLE project_schema")
        c.execute(sql.SQL("DROP FUNCTION {}() CASCADE").format(sql.Identifier(base, "reject_legacy_project_write")))
        for pid in ("old_a", "old_b"):
            c.execute(
                "INSERT INTO project(id,name,workspace_path,payload) VALUES (%s,%s,%s,%s)",
                (pid, pid, "/tmp/" + pid, psycopg.types.json.Jsonb({"id": pid})),
            )
            c.execute(
                "INSERT INTO run(id,project_id,goal,workspace,status,max_iter,budget_cents) "
                "VALUES (%s,%s,'goal','/tmp','WAITING_HUMAN',5,500)",
                ("run_" + pid, pid),
            )
            c.execute(
                "INSERT INTO run_checkpoint VALUES (%s,%s,now())",
                ("run_" + pid, psycopg.types.json.Jsonb({"cache": "paid"})),
            )
            c.execute(
                "INSERT INTO state_record VALUES ('thread',%s,%s,now())",
                (pid, psycopg.types.json.Jsonb({"project_id": pid, "messages": ["private"]})),
            )
            c.execute(
                "INSERT INTO memory(id,project_id,namespace,kind,text,payload) "
                "VALUES (%s,%s,'project','note','private',%s)",
                (pid, pid, psycopg.types.json.Jsonb({"id": pid, "project_id": pid})),
            )
        c.execute(
            "INSERT INTO memory(id,namespace,kind,text,payload) VALUES ('global','global','note','shared',%s)",
            (psycopg.types.json.Jsonb({"id": "global", "project_id": None}),),
        )
    import agentlab.db.isolation as isolation

    original = isolation.clone_tables

    def interrupted(c, base_schema, target):
        original(c, base_schema, target)
        if target.endswith("proj_old_b"):
            raise RuntimeError("simulated migration interruption")

    monkeypatch.setattr(isolation, "clone_tables", interrupted)
    with pytest.raises(RuntimeError, match="interruption"):
        migrate(database_url)
    with psycopg.connect(database_url) as c:
        assert c.execute("SELECT count(*) FROM run").fetchone()[0] == 2
        assert c.execute("SELECT to_regclass(%s)", (base + ".project_schema",)).fetchone()[0] is None
    monkeypatch.setattr(isolation, "clone_tables", original)
    result = migrate(database_url)
    assert set(result["projects"]) == {"old_a", "old_b"}
    assert result["projects"]["old_a"]["run_checkpoint"] == 1
    assert migrate(database_url) == {"already_migrated": True}
    store = PostgresStore(database_url)
    assert len(store.list_runs()) == 2
    assert store.checkpoint("run_old_a") == {"cache": "paid"}
    assert len(store.records("memory")) == 3
    with psycopg.connect(database_url, row_factory=dict_row) as c:
        assert c.execute("SELECT count(*) AS n FROM run").fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM memory").fetchone()["n"] == 1
        for pid in ("old_a", "old_b"):
            target = schema_name(base, pid)
            assert (
                c.execute(sql.SQL("SELECT project_id FROM {}").format(sql.Identifier(target, "run"))).fetchone()[
                    "project_id"
                ]
                == pid
            )
        with pytest.raises(psycopg.errors.RaiseException, match="read-only"):
            c.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(archive, "run")))
    # Fresh projects use the same schema path, never the archived tables.
    fresh = Run(project_id="new_c", goal="new", workspace="/tmp/new")
    store.create_run(fresh)
    assert store.get_run(fresh.id).project_id == "new_c"
    assert len(store.list_runs()) == 3


def test_new_revision_upgrades_existing_project_schemas_atomically(database_url, tmp_path):
    import shutil

    import psycopg
    from psycopg import sql

    from agentlab.adapters.store.postgres import PostgresStore
    from agentlab.db.isolation import schema_name
    from agentlab.db.migrate import upgrade

    store = PostgresStore(database_url)
    store.create_run(Run(project_id="before_one", goal="one", workspace="/tmp/one"))
    store.create_run(Run(project_id="before_two", goal="two", workspace="/tmp/two"))
    with psycopg.connect(database_url) as c:
        base = c.execute("SELECT current_schema()").fetchone()[0]
        # Adopt a pre-fix project without a version table, using the old base version.
        c.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier(schema_name(base, "before_one"), "alembic_version")))
    scripts = tmp_path / "alembic"
    shutil.copytree(Path(__file__).parents[2] / "src/agentlab/db/alembic", scripts)
    revision = scripts / "versions/schema_regression.py"
    revision.write_text("""from alembic import op
revision = "schema_regression"
down_revision = "root_alignment"
def upgrade():
    op.execute("ALTER TABLE run ADD COLUMN regression_marker text")
""")
    upgrade(database_url, script_location=scripts)
    upgrade(database_url, script_location=scripts)
    store.create_run(Run(project_id="after", goal="after", workspace="/tmp/after"))
    schemas = [base, *(schema_name(base, pid) for pid in ("before_one", "before_two", "after"))]
    with psycopg.connect(database_url) as c:
        for schema in schemas:
            assert (
                c.execute(
                    "SELECT count(*) FROM information_schema.columns WHERE table_schema=%s "
                    "AND table_name='run' AND column_name='regression_marker'",
                    (schema,),
                ).fetchone()[0]
                == 1
            )
            assert (
                c.execute(
                    sql.SQL("SELECT version_num FROM {}").format(sql.Identifier(schema, "alembic_version"))
                ).fetchone()[0]
                == "schema_regression"
            )
    (scripts / "versions/failing_revision.py").write_text("""from alembic import op
revision = "failing_revision"
down_revision = "schema_regression"
def upgrade():
    op.execute("ALTER TABLE run ADD COLUMN rollback_marker text")
    if op.get_context().config.attributes["migration_scope"] == "project":
        raise RuntimeError("project migration failed")
""")
    with pytest.raises(RuntimeError, match="project migration failed"):
        upgrade(database_url, script_location=scripts)
    with psycopg.connect(database_url) as c:
        for schema in schemas:
            assert (
                c.execute(
                    "SELECT count(*) FROM information_schema.columns WHERE table_schema=%s "
                    "AND table_name='run' AND column_name='rollback_marker'",
                    (schema,),
                ).fetchone()[0]
                == 0
            )
            assert (
                c.execute(
                    sql.SQL("SELECT version_num FROM {}").format(sql.Identifier(schema, "alembic_version"))
                ).fetchone()[0]
                == "schema_regression"
            )


def test_project_upgrade_head_preserves_base_schema(database_url, tmp_path):
    import shutil

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from agentlab.adapters.store.postgres import PostgresStore
    from agentlab.db.migration_scope import base_structure

    PostgresStore(database_url).create_run(Run(project_id="guard_seed", goal="seed", workspace="/tmp/guard"))
    scripts = tmp_path / "alembic"
    shutil.copytree(Path(__file__).parents[2] / "src/agentlab/db/alembic", scripts)
    # p2_initial reads its packaged SQL relative to the script root.
    shutil.copytree(Path(__file__).parents[2] / "src/agentlab/db/migrations", tmp_path / "migrations")
    engine = create_engine(database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    try:
        with engine.connect() as c:
            base = c.execute(text("SELECT current_schema()")).scalar_one()
            target = base[:20] + "_guard"
            quote = c.dialect.identifier_preparer.quote
            c.execute(text(f"CREATE SCHEMA {quote(target)}"))
            c.commit()
            config = Config()
            config.set_main_option("script_location", str(scripts))
            config.attributes.update(connection=c, migration_scope="project", base_schema=base)
            with c.begin():
                c.execute(text(f"SET LOCAL search_path TO {quote(target)}, {quote(base)}, public"))
                before = base_structure(c, base)

                def base_data():
                    tables = (
                        c.execute(
                            text("SELECT tablename FROM pg_tables WHERE schemaname=:base ORDER BY tablename"),
                            {"base": base},
                        )
                        .scalars()
                        .all()
                    )
                    return {
                        table: list(
                            c.execute(
                                text(
                                    f"SELECT to_jsonb(t)::text FROM {quote(base)}.{quote(table)} t ORDER BY to_jsonb(t)::text"
                                )
                            ).scalars()
                        )
                        for table in tables
                    }

                rows_before = base_data()
                command.upgrade(config, "head")  # replay all shipped revisions in project scope
                assert base_structure(c, base) == before
                assert base_data() == rows_before
            (scripts / "versions/unsafe_base.py").write_text("""from alembic import op
revision = "unsafe_base"
down_revision = "root_alignment"
def upgrade():
    op.execute("ALTER TABLE run_directory ADD COLUMN unsafe_marker text")
""")
            with pytest.raises(RuntimeError, match="changed base schema structure"), c.begin():
                c.execute(text(f"SET LOCAL search_path TO {quote(target)}, {quote(base)}, public"))
                command.upgrade(config, "head")
            assert base_structure(c, base) == before
            c.rollback()
    finally:
        engine.dispose()


def test_root_messages_are_rows_and_legacy_threads_are_migrated(database_url):
    import json

    import psycopg
    from psycopg import sql

    from agentlab.adapters.store.postgres import PostgresStore
    from agentlab.core.conversation import Conversation, Message
    from agentlab.db.isolation import schema_name
    from agentlab.db.migrate import upgrade

    store = PostgresStore(database_url)
    thread = Conversation(project_id='root_rows', title='legacy', messages=[
        Message(author='user', text='question'), Message(author='system', text='progress')])
    # Provision current schema, then restore the exact old conversation representation.
    store.put_record('thread', thread.id, thread.model_dump(mode='json'))
    with psycopg.connect(database_url) as c:
        base = c.execute('SELECT current_schema()').fetchone()[0]
        target = schema_name(base, 'root_rows')
        c.execute(sql.SQL('SET LOCAL search_path TO {}, {}').format(sql.Identifier(target), sql.Identifier(base)))
        c.execute('DROP TABLE root_turn, message, thread')
        c.execute("UPDATE alembic_version SET version_num='project_threads'")
        c.execute("INSERT INTO state_record(kind,key,data) VALUES ('thread',%s,%s::jsonb)",
                  (thread.id, json.dumps(thread.model_dump(mode='json'))))
    upgrade(database_url)
    restored = next(t for t in store.records('thread') if t['id'] == thread.id)
    assert [m['text'] for m in restored['messages']] == ['question', 'progress']
    restored['messages'].append(Message(author='assistant', text='answer').model_dump(mode='json'))
    store.put_record('thread', thread.id, restored)
    with psycopg.connect(database_url) as c:
        rows = c.execute(sql.SQL('SELECT author,seq FROM {} WHERE thread_id=%s ORDER BY seq').format(
            sql.Identifier(target, 'message')), (thread.id,)).fetchall()
        assert rows == [('user', 1), ('system', 2), ('assistant', 3)]
        # Project migration did not rewrite the public/global row set.
        assert c.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(base, 'thread'))).fetchone()[0] == 0
