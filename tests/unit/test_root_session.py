from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from agentlab.adapters.runtime.raw import RawRuntime
from agentlab.api.app import create_app
from agentlab.core.budget import BudgetGuard
from agentlab.core.conversation import RootTurn
from agentlab.core.llm.structured import Completion, StructuredCaller
from agentlab.core.ports import RunContext
from agentlab.core.schemas import AgentInput, Run
from agentlab.core.session.tools import SessionTools
from agentlab.demo import seed_demo_workspace
from tests.unit.test_project_experience import services


def call(name, args=None):
    return Completion(
        "", 10, 5, [{"id": "t1", "type": "function", "function": {"name": name, "arguments": json.dumps(args or {})}}]
    )


def root_runtime(cfg, completions):
    runtime = object.__new__(RawRuntime)
    runtime._caller = StructuredCaller(cfg, AsyncMock(side_effect=completions))
    return runtime


def test_same_repo_new_conversations_ignore_legacy_turn_and_project_caps(tmp_path: Path):
    svc = services(tmp_path)
    svc.cfg.budget.ask.max_turn_cents = 0.001
    project = svc.projects.create("calc", "fix add", str(seed_demo_workspace(tmp_path / "ws")))
    turn = RootTurn(intent="answer", reply="已检查代码")
    # Paid usage exceeds both the old per-turn cap and the old project cap.
    root = root_runtime(svc.cfg, [Completion(turn.model_dump_json(), 2_000_000, 100) for _ in range(3)])
    svc.runtime = lambda name=None, cfg=None: root
    with TestClient(create_app(svc)) as client:
        first = client.post(f"/projects/{project.id}/threads", json={"title": "first"}).json()
        second = client.post(f"/projects/{project.id}/threads", json={"title": "second"}).json()
        for thread in (first, first, second):
            response = client.post(f"/projects/{project.id}/threads/{thread['id']}/messages", json={"text": "检查代码"})
            assert response.status_code == 200, response.text
            assert response.json()["turn"]["reply"] == turn.reply
    records = svc.store.records("root_turn")
    assert len(records) == 3
    assert all(r["status"] == "completed" and r["cost_cents"] > 0.001 for r in records)


@pytest.mark.parametrize("case", ["entry", "document", "weather", "task", "inspect"])
def test_five_discovery_conversations(tmp_path: Path, case: str):
    svc = services(tmp_path)
    ws = seed_demo_workspace(tmp_path / "ws")
    project = svc.projects.create("calc", "fix add", str(ws))
    turn = {
        "entry": RootTurn(intent="answer", reply="入口是 calc.py", sources=[{"kind": "file", "ref": "calc.py"}]),
        "document": RootTurn(intent="answer", reply="文档说使用 Python", sources=[{"kind": "memory", "ref": "doc"}]),
        "weather": RootTurn(intent="clarify", reply="无法获取实时天气,请提供位置。"),
        "task": RootTurn(intent="task", reply="交给团队修复 add", task="Fix calc.add so tests pass"),
        "inspect": RootTurn(intent="clarify", reply="你想检查哪个函数?"),
    }[case]
    completions = []
    if case == "entry":
        completions.append(call("file_read", {"path": "calc.py"}))
    if case == "document":
        import asyncio

        asyncio.run(svc.knowledge.ingest("design.md", b"Python is the project implementation language", project.id))
        item = svc.knowledge.memory.items_in("project", project.id)[0]
        turn.sources[0].ref = item.id
        completions.append(call("memory_search", {"query": "Python"}))
    completions.append(Completion(turn.model_dump_json(), 10, 5))
    root = root_runtime(svc.cfg, completions)
    original = svc.runtime
    svc.runtime = lambda name=None, cfg=None: root if name is None else original(name, cfg)
    # Driver calls runtime(None), so use a dispatcher that retains the fake loop runtime.
    loop_runtime = original("fake")

    class Runtime:
        async def run_agent(self, role, inp, out, ctx):
            return await (root if role == "root" else loop_runtime).run_agent(role, inp, out, ctx)

        async def run_parallel(self, inputs, out, ctx):
            return await loop_runtime.run_parallel(inputs, out, ctx)

    svc.runtime = lambda name=None, cfg=None: Runtime()
    published = []
    svc.bus.listeners.append(published.append)
    with TestClient(create_app(svc)) as client:
        thread = client.post(f"/projects/{project.id}/threads", json={"title": "chat"}).json()
        result = client.post(f"/projects/{project.id}/threads/{thread['id']}/messages", json={"text": case})
        assert result.status_code == 200, result.text
        data = result.json()
        assert data["turn"]["intent"] == turn.intent
        assert data["message"]["author"] == "assistant"
        assert bool(data["run"]) == (case == "task")
        if case != "task":
            assert not svc.store.list_runs()
        else:
            import time

            # The fake loop still runs real pytest subprocesses for each Gate.
            # Cold CI runners can take longer than five seconds to reach signoff.
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                messages = client.get(f"/projects/{project.id}/threads").json()[0]["messages"]
                if any(m["kind"] == "summary" for m in messages) and any(m["kind"] == "approval" for m in messages):
                    break
                time.sleep(0.05)
            assert any(m["kind"] == "progress" for m in messages)
            run = svc.store.get_run(data["run"]["id"])
            diagnostic = f"run={run.status}, paused_reason={run.paused_reason}, messages={messages}"
            assert any(m["kind"] == "approval" for m in messages), diagnostic
            assert any(m["kind"] == "summary" for m in messages), diagnostic
            assert all("step.finished:" not in m["text"] for m in messages)
            assert len([e for e in published if e.type == "turn.finished"]) >= 2
        turns = svc.store.records("root_turn")
        assert turns[0]["cost_cents"] > 0 and turns[0]["attempts"][0]["prompt_ref"]
        if completions[:-1]:
            assert turns[0]["tool_calls"][0]["status"] == "started"
            assert turns[0]["tool_calls"][1]["status"] == "completed"
        if case == "document":
            assert "Python" in turns[0]["tool_calls"][1]["result"][0]["text"]
            assert data["message"]["sources"][0]["ref"] == item.id
        usage = client.get(f"/projects/{project.id}/usage").json()
        assert usage["conversation_cost_cents"] > 0


async def test_tools_stay_available_budgeted_and_replayed(cfg):
    cfg = cfg.model_copy(deep=True)
    cfg.model_policy.roles["root"].fallback = []
    calls = AsyncMock(
        side_effect=[call("file_list") for _ in range(8)]
        + [Completion(RootTurn(intent="answer", reply="Collected evidence").model_dump_json(), 10, 5)]
    )
    run = Run(goal="inspect", workspace=".", budget_cents=10000)
    guard = BudgetGuard(run, 0.8, lambda _: None)
    execute = AsyncMock(return_value=["calc.py"])
    records = []
    checks = []

    def check(estimate):
        checks.append(estimate)
        guard.check(estimate)

    ctx = RunContext(
        run, check, guard.record, tool_specs=[{"type": "function"}], execute_tool=execute, record_tool=records.append
    )
    result = await StructuredCaller(cfg, calls).call(
        "root", AgentInput(run_id=run.id, iteration=0, goal="inspect"), RootTurn, ctx
    )
    assert result.output.reply == "Collected evidence"
    # Tools remain available after many calls.
    assert "tools" in calls.call_args.kwargs
    assert execute.await_count == 8 and len(records) == 16
    assert checks.count(0) == 8
    assert run.tokens_in == 90
    transcript = calls.call_args.kwargs["messages"]
    assert len([m for m in transcript if m["role"] == "tool"]) == 8


async def test_tools_reuse_workspace_boundaries_and_scope(tmp_path):
    svc = services(tmp_path)
    ws = seed_demo_workspace(tmp_path / "ws")
    (ws / ".env").write_text("SECRET=hidden")
    (ws / "escape.py").symlink_to(tmp_path / "outside")
    from agentlab.adapters.workspace import GitWorkspace

    workspace = GitWorkspace(ws)
    await workspace.ensure_repo()
    tools = SessionTools(workspace, svc.knowledge, svc.store, "p", "t")
    assert ".env" not in await tools.execute("file_list", {})
    with pytest.raises(PermissionError):
        await tools.execute("file_read", {"path": ".env"})
    with pytest.raises(PermissionError):
        await tools.execute("file_read", {"path": "../outside"})
    for project, thread in [("p", "other"), ("other", "t")]:
        svc.store.save_run(Run(project_id=project, thread_id=thread, workspace=str(ws), goal="secret"))
    assert await tools.execute("run_status", {}) == []
    workspace.close()


def test_global_chat_and_busy_workspace_reply(tmp_path):
    svc = services(tmp_path)
    original = svc.runtime

    class Runtime:
        async def run_agent(self, role, inp, out, ctx):
            if role == "root":
                from agentlab.core.schemas import AgentResult, Usage

                return AgentResult(
                    role=role,
                    output=RootTurn(intent="task", reply="Will fix add", task="Fix add"),
                    alias="fake",
                    model="fake",
                    usage=Usage(cost_cents=0.1),
                )
            return await original("fake").run_agent(role, inp, out, ctx)

        async def run_parallel(self, inputs, out, ctx):
            return await original("fake").run_parallel(inputs, out, ctx)

    svc.runtime = lambda name=None, cfg=None: Runtime()
    with TestClient(create_app(svc)) as client:
        global_thread = client.post("/threads", json={"title": "global"}).json()
        result = client.post(f"/threads/{global_thread['id']}/messages", json={"text": "fix add"}).json()
        assert result["turn"]["intent"] == "clarify" and result["run"] is None
        assert not svc.store.list_runs()
        ws = seed_demo_workspace(tmp_path / "busy")
        project = svc.projects.create("busy", "fix", str(ws))
        thread = client.post(f"/projects/{project.id}/threads", json={"title": "busy"}).json()
        svc.store.create_run(Run(project_id=project.id, workspace=str(ws), goal="existing"))
        result = client.post(f"/projects/{project.id}/threads/{thread['id']}/messages", json={"text": "fix add"}).json()
        # A task executing in the same repository blocks a new one (a paused task would not).
        assert result["run"] is None and "worktree" in result["message"]["text"]
        assert len(svc.store.list_runs()) == 1
        # A foreign project cannot read or post to this conversation.
        foreign = svc.projects.create("foreign", "fix", str(seed_demo_workspace(tmp_path / "foreign")))
        assert (
            client.post(f"/projects/{foreign.id}/threads/{thread['id']}/messages", json={"text": "hi"}).status_code
            == 404
        )


def test_scorecards_fail_only_on_hard_errors():
    from agentlab.evaluation.baseline import check, scorecard

    soft = scorecard("soft", [check("warning", False, "warning", severity="soft")], 1)
    assert soft["passed"] and soft["soft_warning_count"] == 1 and soft["blind_spot_count"] == 1
    hard = scorecard("hard", [check("test", False, "failed")])
    assert not hard["passed"] and hard["verdict"] == "FAIL" and hard["hard_error_count"] == 1


async def test_coder_tools_write_check_and_checkpoint(tmp_path):
    svc = services(tmp_path)
    ws = seed_demo_workspace(tmp_path / "tools")
    driver = svc.driver(ws, "fake", "python")
    await driver.workspace.ensure_repo()
    run = await driver.create_async("Fix add")
    fixed = 'def add(a, b):\n    """Add numbers."""\n    return a + b\n'
    raw = root_runtime(
        driver.cfg,
        [
            call("workspace_read", {"path": "calc.py"}),
            call("workspace_write", {"path": "calc.py", "content": fixed}),
            call("gate_run"),
            Completion('{"edits":[]}', 20, 10),
        ],
    )
    fake = driver.runtime

    class Runtime:
        async def run_agent(self, role, inp, out, ctx):
            return await (raw if role == "coder" else fake).run_agent(role, inp, out, ctx)

        async def run_parallel(self, inputs, out, ctx):
            return await fake.run_parallel(inputs, out, ctx)

    driver.runtime = Runtime()
    finished = await driver.run(run.id)
    assert finished.paused_reason == "signoff"
    assert (ws / "calc.py").read_text() == fixed
    tool_events = [e for e in svc.store.events(run.id) if e.type == "step.tool_call"]
    assert len(tool_events) == 6 and all(e.actor == "coder" for e in tool_events)
    assert svc.blobs.get(tool_events[-1].payload["content_ref"])
    assert "calc.py" in svc.store.checkpoint(run.id)["workspace"]["edited_paths"]
    driver.workspace.close()


async def test_worker_grants_and_sensitive_writes(tmp_path):
    from agentlab.core.llm.tools import WorkerTools

    svc = services(tmp_path)
    driver = svc.driver(seed_demo_workspace(tmp_path / "grants"), "fake", "python")

    async def memory(query):
        return {}

    reviewer = WorkerTools(
        "arch-reviewer", ["workspace_read", "workspace_write", "gate_run"], driver.workspace, driver.gate, memory
    )
    assert {s["function"]["name"] for s in reviewer.specs} == {
        "workspace_read", "workspace_read_next", "workspace_read_status", "workspace_excerpt",
    }
    with pytest.raises(ValueError, match="not granted"):
        await reviewer.execute("workspace_write", {"path": "calc.py", "content": "unsafe"})
    coder = WorkerTools("coder", ["workspace_write"], driver.workspace, driver.gate, memory)
    with pytest.raises(PermissionError):
        await coder.execute("workspace_write", {"path": ".env", "content": "unsafe"})
    driver.workspace.close()


def test_reviewer_diversity_ignores_models_below_reviewer_tier(tmp_path):
    from agentlab.core.project_config import Binding, Dispatch, ProjectSettings, worker_roles

    svc = services(tmp_path)
    bindings = {role: Binding(alias="strong", task="review") for role in worker_roles(svc.cfg)}
    bindings["test-style-reviewer"] = Binding(alias="cheap", task="review style")
    # Cheap is a distinct model, but cannot be assigned to correctness/architecture.
    Dispatch(assignments=bindings, reviewers=svc.cfg.reviewer_roles).validate_for(svc.cfg, ProjectSettings(allowed_aliases=["strong", "cheap"]))
    with pytest.raises(ValueError, match="different model IDs"):
        Dispatch(assignments=bindings, reviewers=svc.cfg.reviewer_roles).validate_for(
            svc.cfg, ProjectSettings(allowed_aliases=["strong", "strong-alt", "cheap"])
        )


def test_schema_provision_fast_path_and_race_recheck():
    from agentlab.db.isolation import provision

    class Result:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

    class Connection:
        def __init__(self, existing):
            self.existing, self.statements, self.reads = existing, [], 0

        def execute(self, statement, params=()):
            text = statement if isinstance(statement, str) else statement.as_string()
            self.statements.append(text)
            if "SELECT schema_name" in text:
                self.reads += 1
                return Result({"schema_name": "proj_existing"} if self.existing or self.reads > 1 else None)
            return Result(None)

    existing = Connection(True)
    assert provision(existing, "public", "p") == "proj_existing"
    assert not any("pg_advisory_xact_lock(hashtext" in sql for sql in existing.statements)
    race = Connection(False)
    assert provision(race, "public", "p") == "proj_existing"
    assert race.reads == 2 and any("pg_advisory_xact_lock(hashtext" in sql for sql in race.statements)


@pytest.mark.parametrize("error", [False, True])
async def test_tool_errors_and_large_results_allow_answer(cfg, error):
    cfg = cfg.model_copy(deep=True)
    cfg.model_policy.roles["root"].fallback = []
    chat = AsyncMock(
        side_effect=[
            call("web_search"),
            Completion(
                RootTurn(intent="answer", reply="Search unavailable" if error else "Found evidence").model_dump_json(),
                10,
                5,
            ),
        ]
    )
    execute = (
        AsyncMock(side_effect=RuntimeError("private gateway details"))
        if error
        else AsyncMock(return_value={"text": "x" * 100000})
    )
    run = Run(goal="search", workspace=".")
    ctx = RunContext(run, lambda _: None, tool_specs=[{"type": "function"}], execute_tool=execute)
    result = await StructuredCaller(cfg, chat).call(
        "root", AgentInput(run_id=run.id, iteration=0, goal="search"), RootTurn, ctx
    )
    assert result.output.reply
    content = chat.call_args.kwargs["messages"][-1]["content"]
    assert len(content.encode()) <= 16384
    assert "private gateway details" not in content
    assert ("RuntimeError" if error else "truncated") in content


def test_append_only_message_storage_does_not_scan_records(tmp_path):
    from agentlab.core.conversation import Conversation, Message
    from agentlab.core.session.store import append_message, get_thread

    svc = services(tmp_path)
    thread = Conversation(project_id=None, title="chat")
    svc.store.put_record("thread", thread.id, thread.model_dump(mode="json"))
    svc.store.records = lambda _: (_ for _ in ()).throw(AssertionError("must not scan records"))
    for index in range(3):
        assert append_message(svc.store, thread.id, None, Message(author="user", text="hi")).seq == index + 1
    assert len(get_thread(svc.store, thread.id, None).messages) == 3


@pytest.mark.parametrize("runtime, sandbox", [("fake", "local"), ("raw", "docker")])
async def test_eval_sandbox_selected_before_model_execution(tmp_path, monkeypatch, runtime, sandbox):
    from agentlab.evaluation import baseline

    monkeypatch.setattr(baseline, "evaluation_workspace_root", lambda: tmp_path)
    monkeypatch.setenv("AGENTLAB_DATA_DIR", str(tmp_path / "state"))
    manifest = tmp_path / "baseline.json"
    manifest.write_text('{"tasks": []}')

    class StopBeforeExecution(Exception):
        pass

    def build(settings):
        assert settings.sandbox == sandbox
        assert settings.data_dir.parent.parent == tmp_path
        raise StopBeforeExecution

    monkeypatch.setattr(baseline, "build_services", build)
    with pytest.raises(StopBeforeExecution):
        await baseline.evaluate(manifest, runtime)


async def test_each_approval_gets_its_own_summary(tmp_path):
    from agentlab.core.conversation import Conversation
    from agentlab.core.schemas import Approval, RunStatus
    from agentlab.core.session.store import get_thread
    from agentlab.services import MemoryHooks

    svc = services(tmp_path)
    thread = Conversation(project_id="p", title="chat")
    svc.store.put_record("thread", thread.id, thread.model_dump(mode="json"))
    run = Run(goal="fix", workspace=".", project_id="p", thread_id=thread.id, status=RunStatus.WAITING_HUMAN)
    svc.store.create_run(run)
    hooks = MemoryHooks(svc.knowledge, svc.projects)
    first = Approval(run_id=run.id, reason="budget_exceeded", on_approve=RunStatus.CODING)
    svc.store.create_approval(first)
    await hooks.summarize_run(run)
    await hooks.summarize_run(run)
    first.status = "approved"
    svc.store.save_approval(first)
    second = Approval(run_id=run.id, reason="signoff", on_approve=RunStatus.DONE)
    svc.store.create_approval(second)
    await hooks.summarize_run(run)
    await hooks.summarize_run(run)
    summaries = [m for m in get_thread(svc.store, thread.id, "p").messages if m.kind == "summary"]
    assert [m.payload["approval_id"] for m in summaries] == [first.id, second.id]


async def test_root_read_only_git_and_missing_files(tmp_path):
    import subprocess

    from agentlab.adapters.workspace import GitWorkspace, WorkspaceNotFound

    svc = services(tmp_path)
    ws = tmp_path / "git-project"
    ws.mkdir()
    workspace = GitWorkspace(ws)
    await workspace.ensure_repo()
    tools = SessionTools(workspace, svc.knowledge, svc.store, "p", "t")

    def git(*args):
        return subprocess.run(["git", "-C", str(ws), *args], check=True, capture_output=True).stdout

    git("checkout", "-b", "module-branch")
    (ws / "module.py").write_text("VALUE = 42\n")
    git("add", "module.py")
    git("-c", "user.name=test", "-c", "user.email=test@local", "commit", "-m", "add module")
    git("checkout", "-b", "without-module", "HEAD~1")
    before = git("status", "--porcelain")
    with pytest.raises(WorkspaceNotFound) as error:
        await tools.execute("file_read", {"path": "module.py"})
    assert error.value.kind == "not_found"
    assert "module-branch" in (await tools.execute("git_branch", {}))["text"]
    assert "add module" in (await tools.execute("git_log", {"ref": "module-branch"}))["text"]
    assert "module.py" in (await tools.execute("git_show", {"ref": "module-branch", "path": ""}))["text"]
    assert "VALUE = 42" in (await tools.execute("git_show", {"ref": "module-branch", "path": "module.py"}))["text"]
    assert "VALUE = 42" in (await tools.execute("git_diff", {"ref": "module-branch", "path": "module.py"}))["text"]
    await tools.execute("git_status", {})
    for ref in ["--output=/tmp/escape", "HEAD:module.py", "HEAD; touch bad"]:
        with pytest.raises(ValueError):
            await tools.execute("git_show", {"ref": ref, "path": "module.py"})
    for path in [".env", "../outside", ".git/config"]:
        with pytest.raises(PermissionError):
            await tools.execute("git_show", {"ref": "module-branch", "path": path})
    assert git("status", "--porcelain") == before
    assert git("branch", "--show-current").strip() == b"without-module"
    workspace.close()


async def test_stop_ends_a_running_root_turn(tmp_path):
    import asyncio

    import httpx

    svc = services(tmp_path)
    started = asyncio.Event()

    class Hanging:
        async def run_agent(self, *args, **kwargs):
            started.set()
            await asyncio.Event().wait()

    svc.runtime = lambda name=None, cfg=None: Hanging()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(svc)), base_url="http://t") as client:
        thread = (await client.post("/threads", json={"title": "t"})).json()
        sending = asyncio.create_task(client.post(f"/threads/{thread['id']}/messages", json={"text": "hi"}))
        await asyncio.wait_for(started.wait(), 5)
        assert (await client.post(f"/threads/{thread['id']}/turn/cancel")).json() == {"stopped": True}
        response = await asyncio.wait_for(sending, 5)
        assert response.status_code == 200, response.text
        assert response.json()["turn"]["reply"] == "已停止本轮回答。"
        assert (await client.post(f"/threads/{thread['id']}/turn/cancel")).json() == {"stopped": False}
    assert [r["status"] for r in svc.store.records("root_turn")] == ["cancelled"]
