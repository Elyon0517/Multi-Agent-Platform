from __future__ import annotations

import asyncio
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from agentlab.adapters.events import InProcessEventBus
from agentlab.adapters.runtime.raw import OpenAICompatChat, RawRuntime
from agentlab.adapters.workspace import GitWorkspace
from agentlab.api.app import create_app
from agentlab.bootstrap import build_services
from agentlab.cli.main import _drive
from agentlab.core.budget import BudgetExceeded, BudgetGuard
from agentlab.core.llm.retry import AttemptLog, LlmError, NonRetryable, RetriesExhausted, Retryable, call_with_retry
from agentlab.core.llm.structured import Completion, StructuredCaller
from agentlab.core.loop.arbiter import arbitrate
from agentlab.core.memory.documents import chunk
from agentlab.core.ports import RunContext
from agentlab.core.schemas import (
    AgentInput,
    ArbiterAction,
    CoderOutput,
    Event,
    EventType,
    FileEdit,
    Run,
    RunStatus,
)
from agentlab.settings import Settings
from tests.conftest import CONFIG_DIR, finding, verdict
from tests.unit.test_driver import make_driver


@pytest.mark.parametrize("error", [NonRetryable("auth_401_403"), RetriesExhausted(4, ["read_timeout"]), LlmError("bad JSON"), RuntimeError("git failed")])
async def test_failures_pause_instead_of_stranding_run(cfg, tmp_path, error):  # type: ignore[no-untyped-def]
    def fail(_):  # type: ignore[no-untyped-def]
        raise error
    driver = await make_driver(cfg, tmp_path, {"coder": fail})
    run = await driver.run(driver.create("fix add").id)
    assert run.status == RunStatus.WAITING_HUMAN
    approval = driver.store.pending_approval(run.id)
    assert approval.reason == "execution_error" and approval.on_approve == RunStatus.CODING
    assert "git failed" not in json.dumps(approval.payload)
    from agentlab.adapters.runtime.fake import FakeRuntime
    from agentlab.demo import demo_scripts
    old_runtime = driver.runtime
    driver.runtime_factory = lambda: FakeRuntime(demo_scripts())
    assert driver.decide(run.id, "approve").status == RunStatus.CODING
    assert driver.runtime is not old_runtime


async def test_escape_is_an_approval_and_never_writes_outside(cfg, tmp_path):  # type: ignore[no-untyped-def]
    def escape(_):  # type: ignore[no-untyped-def]
        return CoderOutput(edits=[FileEdit(path="../escape.py", content="bad")])
    driver = await make_driver(cfg, tmp_path, {"coder": escape})
    run = await driver.run(driver.create("fix add").id)
    assert run.paused_reason == "workspace_escape"
    assert not (tmp_path / "escape.py").exists()
    assert driver.decide(run.id, "approve").status == RunStatus.CODING


async def test_budget_approval_requires_an_increase_and_auto_approve_stops(cfg, tmp_path):  # type: ignore[no-untyped-def]
    driver = await make_driver(cfg, tmp_path)
    svc = build_services(Settings(config_dir=CONFIG_DIR, data_dir=tmp_path, _env_file=None))
    svc.store = driver.store
    run = await _drive(svc, driver, driver.create("fix add", budget_cents=0.01), True)
    assert run.paused_reason == "budget_exceeded"
    before = len(driver.store.events(run.id))
    with pytest.raises(ValueError, match="increase budget"):
        driver.decide(run.id, "approve")
    assert len(driver.store.events(run.id)) == before
    assert driver.decide(run.id, "reject").status == RunStatus.PLANNING


async def test_non_signoff_approval_never_marks_done(cfg, tmp_path):  # type: ignore[no-untyped-def]
    def stuck(_):  # type: ignore[no-untyped-def]
        return CoderOutput(edits=[FileEdit(path="calc.py", content="def add(a,b):\n    return 0\n")])
    driver = await make_driver(cfg, tmp_path, {"coder": stuck})
    run = await driver.run(driver.create("fix add").id)
    assert run.paused_reason == "oscillation_detected"
    assert driver.decide(run.id, "approve").status == RunStatus.CODING


async def test_reviewer_steps_match_the_reviewed_iteration(cfg, tmp_path):  # type: ignore[no-untyped-def]
    driver = await make_driver(cfg, tmp_path)
    run = await driver.run(driver.create("fix add").id)
    for iteration in driver.store.iterations(run.id):
        if iteration.verdicts:
            steps = [step for step in driver.store.steps(run.id) if step.role in cfg.reviewer_roles and step.iteration_n == iteration.n]
            assert len(steps) == 3
            assert all(f.reviewer_id == v.reviewer_id for v in iteration.verdicts for f in v.findings)


def test_identity_spoof_and_unrelated_same_line_do_not_conflict():
    a = finding(issue="bug").model_copy(update={"reviewer_id": "spoof-a"})
    b = finding(issue="name", sev="minor").model_copy(update={"reviewer_id": "spoof-b"})
    decision = arbitrate([verdict("real", a, b), verdict("other")], 0.7)
    assert decision.action == ArbiterAction.BACK_TO_CODER
    assert decision.instructions[0].reviewer_id == "real"
    assert arbitrate([verdict("real", a), verdict("other", b)], 0.7).action == ArbiterAction.BACK_TO_CODER


def test_block_without_hard_findings_is_not_signoff():
    v = verdict("reviewer").model_copy(update={"verdict": "BLOCK"})
    assert not v.is_signoff
    assert arbitrate([v], 0.7).reason == "inconsistent_verdict"


async def test_subscribe_registers_before_first_next():
    bus = InProcessEventBus()
    live = bus.subscribe("r")
    event = Event(run_id="r", seq=1, type=EventType.RUN_STATUS)
    bus.publish(event)
    assert await asyncio.wait_for(anext(live), 0.2) == event
    await live.aclose()
    assert not bus._subs["r"]


async def test_sse_history_live_gap_and_last_event_id(tmp_path):  # type: ignore[no-untyped-def]
    svc = build_services(Settings(config_dir=CONFIG_DIR, data_dir=tmp_path, _env_file=None))
    run = svc.store.create_run(Run(goal="g", workspace="."))
    for _ in range(3):
        svc.store.append_event(Event(run_id=run.id, type=EventType.RUN_STATUS))
    app = create_app(svc)
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/runs/{run_id}/events")
    request = Request({"type": "http", "headers": [(b"last-event-id", b"1")]})
    response = await endpoint(run.id, request, 0)
    stream = response.body_iterator
    assert (await anext(stream))["id"] == "2"
    event = svc.store.append_event(Event(run_id=run.id, type=EventType.APPROVAL_REQUESTED))
    svc.bus.publish(event)
    assert (await anext(stream))["id"] == "3"
    assert (await asyncio.wait_for(anext(stream), 0.2))["id"] == "4"
    await stream.aclose()
    assert not svc.bus._subs[run.id]


async def test_diff_is_run_scoped_secret_filtered_and_index_preserving(tmp_path):  # type: ignore[no-untyped-def]
    (tmp_path / "source.py").write_text("user change\n")
    (tmp_path / ".env").write_text("private-key-must-not-leak")
    (tmp_path / "credentials.json").write_text("private-key-must-not-leak")
    (tmp_path / "public.py").write_text('key = "opaque-gateway-key"')
    workspace = GitWorkspace(tmp_path, secrets=("opaque-gateway-key",))
    await workspace.ensure_repo()
    (tmp_path / "source.py").write_text("uncommitted user change\n")
    workspace.begin_run()
    before = subprocess.check_output(["git", "-C", str(tmp_path), "ls-files", "--stage"])
    workspace.apply_edits([FileEdit(path="new.py", content="own change\n")])
    diff = await workspace.diff()
    assert "own change" in diff and "source.py" not in diff and "private-key" not in diff
    assert "public.py" not in await workspace.context_files()
    assert subprocess.check_output(["git", "-C", str(tmp_path), "ls-files", "--stage"]) == before


async def test_invalid_json_usage_is_charged_even_after_repair_exhaustion(cfg):  # type: ignore[no-untyped-def]
    run = Run(goal="g", workspace=".")
    guard = BudgetGuard(run, .8, lambda _: None)
    ctx = RunContext(run, guard.check, guard.record, guard.reserve, guard.release)
    caller = StructuredCaller(cfg, AsyncMock(return_value=Completion("not json", 100, 10)))
    with pytest.raises(LlmError):
        await caller.call("coder", AgentInput(run_id=run.id, iteration=1, goal="g"), CoderOutput, ctx)
    assert run.tokens_in == 300 and run.tokens_out == 30
    assert run.cost_cents == pytest.approx(cfg.models.aliases["strong"].cost_cents(300, 30))
    assert guard._reserved == 0


async def test_parallel_budget_reservations_and_completed_usage_survive_failure(cfg):  # type: ignore[no-untyped-def]
    run = Run(goal="g", workspace=".", budget_cents=40)
    guard = BudgetGuard(run, .8, lambda _: None)
    ctx = RunContext(run, guard.check, guard.record, guard.reserve, guard.release)
    async def concurrent_chat(**kwargs):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.01)
        return Completion('{"reviewer_id":"r","verdict":"APPROVE"}', 100, 10)
    caller = StructuredCaller(cfg, concurrent_chat)
    runtime = object.__new__(RawRuntime)
    runtime._caller = caller
    from agentlab.core.llm.retry import ParallelFailure
    from agentlab.core.schemas import Verdict
    inputs = {role: AgentInput(run_id=run.id, iteration=1, goal="g") for role in cfg.reviewer_roles}
    with pytest.raises(ParallelFailure) as failure:
        await runtime.run_parallel(inputs, Verdict, ctx)
    assert isinstance(failure.value.cause, BudgetExceeded)
    assert len(failure.value.results) == 1
    assert run.tokens_in == 100 and run.tokens_out == 10 and guard._reserved == 0


async def test_retry_configuration_can_disable_retries(cfg):  # type: ignore[no-untyped-def]
    call = AsyncMock(side_effect=Retryable("server_error_5xx"))
    policy = cfg.retry.llm_call.model_copy(update={"retry_on": []})
    with pytest.raises(NonRetryable):
        await call_with_retry(call, policy, AttemptLog(), lambda: None)
    assert call.await_count == 1


async def test_refusal_is_not_an_empty_response_and_schema_is_json():
    create = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, refusal="refused"), finish_reason="stop")], usage=SimpleNamespace(prompt_tokens=9, completion_tokens=2)))
    chat = object.__new__(OpenAICompatChat)
    chat._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with pytest.raises(NonRetryable) as exc:
        await chat(model="m", system="s", messages=[], temperature=0, schema={"additionalProperties": False})
    assert exc.value.kind == "content_policy_refusal" and exc.value.tokens_in == 9
    content = create.call_args.kwargs["messages"][0]["content"]
    assert json.loads(content.split("Respond with JSON matching:\n")[1]) == {"additionalProperties": False}


async def test_project_planning_failure_is_budgeted_and_does_not_publish(cfg, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    svc = build_services(Settings(config_dir=CONFIG_DIR, data_dir=tmp_path, _env_file=None))
    async def chat(**kwargs):  # type: ignore[no-untyped-def]
        return Completion("invalid", 100, 10)
    runtime = object.__new__(RawRuntime)
    runtime._caller = StructuredCaller(cfg, chat)
    monkeypatch.setattr(type(svc), "runtime", lambda *args: runtime)
    with TestClient(create_app(svc)) as client:
        response = client.post("/projects", json={"name":"p", "goal":"g", "workspace":str(tmp_path)})
        assert response.status_code == 502
        assert client.get("/projects").json() == []
        ledger = client.get("/project-planning").json()
        assert ledger[0]["cost_cents"] > 0 and ledger[0]["tokens_in"] == 300


async def test_document_versions_are_retired_not_deleted(tmp_path):  # type: ignore[no-untyped-def]
    svc = build_services(Settings(config_dir=CONFIG_DIR, data_dir=tmp_path, _env_file=None))
    await svc.knowledge.ingest("notes.txt", b"first version")
    first = next(iter(svc.knowledge.memory._items.values()))
    await svc.knowledge.ingest("notes.txt", b"second version")
    assert first.valid_to and first.superseded_by
    assert len(svc.knowledge.memory._items) == 2
    assert svc.knowledge.delete("notes.txt") == 1
    assert len(svc.knowledge.memory._items) == 2 and not svc.knowledge.documents()


def test_chunks_never_exceed_size():
    text = "a" * 1000 + "\n\n" + "b" * 1200 + "\n\n" + "c" * 1400
    chunks = list(chunk(text))
    assert all(0 < len(part) <= 1200 for part in chunks)
    assert chunks[-1].endswith("c")


async def test_project_planner_budget_stops_before_any_request(cfg, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    svc = build_services(Settings(config_dir=CONFIG_DIR, data_dir=tmp_path, _env_file=None))
    request = AsyncMock(return_value=Completion('{"phases":[]}', 100, 10))
    runtime = object.__new__(RawRuntime)
    runtime._caller = StructuredCaller(cfg, request)
    monkeypatch.setattr(type(svc), "runtime", lambda *args: runtime)
    with TestClient(create_app(svc)) as client:
        response = client.post("/projects", json={"name": "p", "goal": "g", "workspace": str(tmp_path), "budget_cents": .001})
        assert response.status_code == 409
        assert client.get("/projects").json() == []
        assert client.get("/project-planning").json()[0]["cost_cents"] == 0
    request.assert_not_awaited()


async def test_paid_empty_response_usage_survives_retry_policy_failure(cfg):  # type: ignore[no-untyped-def]
    run = Run(goal="g", workspace=".")
    guard = BudgetGuard(run, .8, lambda _: None)
    ctx = RunContext(run, guard.check, guard.record, guard.reserve, guard.release)
    error = Retryable("empty_response")
    error.tokens_in, error.tokens_out = 30, 5
    policy = cfg.model_copy(deep=True)
    policy.retry.llm_call.num_retries = 0
    policy.model_policy.roles["coder"].fallback = []
    caller = StructuredCaller(policy, AsyncMock(side_effect=error))
    with pytest.raises(RetriesExhausted):
        await caller.call("coder", AgentInput(run_id=run.id, iteration=1, goal="g"), CoderOutput, ctx)
    assert run.tokens_in == 30 and run.tokens_out == 5 and guard._reserved == 0


async def test_do_not_retry_has_precedence_over_retry_on(cfg):  # type: ignore[no-untyped-def]
    call = AsyncMock(side_effect=Retryable("server_error_5xx"))
    policy = cfg.retry.llm_call.model_copy(update={"retry_on": ["server_error_5xx"], "do_not_retry_on": ["server_error_5xx"]})
    with pytest.raises(NonRetryable):
        await call_with_retry(call, policy, AttemptLog(), lambda: None)
    assert call.await_count == 1


async def test_fallback_step_usage_includes_paid_failed_alias(cfg):  # type: ignore[no-untyped-def]
    policy = cfg.model_copy(deep=True)
    policy.retry.llm_call.num_retries = 0
    failure = Retryable("server_error_5xx")
    failure.tokens_in, failure.tokens_out = 30, 5
    chat = AsyncMock(side_effect=[failure, Completion('{"edits":[]}', 100, 10)])
    run = Run(goal="g", workspace=".")
    guard = BudgetGuard(run, .8, lambda _: None)
    ctx = RunContext(run, guard.check, guard.record, guard.reserve, guard.release)
    result = await StructuredCaller(policy, chat).call("coder", AgentInput(run_id=run.id, iteration=1, goal="g"), CoderOutput, ctx)
    assert result.alias == "root"
    assert result.usage.tokens_in == run.tokens_in == 130
    assert result.usage.tokens_out == run.tokens_out == 15
    assert result.usage.cost_cents == run.cost_cents
