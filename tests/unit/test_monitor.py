from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from agentlab.api.app import create_app
from agentlab.core.conversation import RootTurn
from agentlab.core.llm.retry import LlmError, NonRetryable, Retryable
from agentlab.core.llm.structured import Completion, StructuredCaller
from agentlab.core.monitor import UsageRecorder, summarize
from agentlab.core.ports import RunContext
from agentlab.core.schemas import AgentInput, Run, Usage
from agentlab.demo import seed_demo_workspace
from tests.unit.test_project_experience import services
from tests.unit.test_root_session import root_runtime


async def test_two_projects_fake_runs_and_root_turn_match_records(tmp_path: Path):
    svc = services(tmp_path)
    for name in ("one", "two"):
        ws = seed_demo_workspace(tmp_path / name)
        project = svc.projects.create(name, "fix add", str(ws))
        driver = svc.driver(ws, "fake", "python", project.id)
        await driver.workspace.ensure_repo()
        run = await driver.create_async("fix add", project_id=project.id)
        await driver.run(run.id)
    steps = [s for r in svc.store.list_runs() for s in svc.store.steps(r.id)]
    runtime = root_runtime(svc.cfg, [Completion(RootTurn(intent="answer", reply="Hello").model_dump_json(), 17, 9)])
    svc.runtime = lambda name=None, cfg=None: runtime
    with TestClient(create_app(svc)) as client:
        thread = client.post("/threads", json={"title": "Hello"}).json()
        response = client.post(f"/threads/{thread['id']}/messages", json={"text": "Hello"})
        assert response.status_code == 200, response.text
        data = client.get("/monitor/usage").json()
        assert "arbiter" not in {r["role"] for r in data["agents"]}
        assert data["total"]["calls"] == len(steps) + 1
        assert data["total"]["tokens_in"] == sum(s.usage.tokens_in for s in steps) + 17
        assert data["total"]["tokens_out"] == sum(s.usage.tokens_out for s in steps) + 9
        for row in data["agents"]:
            if row["role"] == "root":
                assert row["tokens_in"] == svc.store.records("root_turn")[0]["tokens_in"]
                continue
            matching = [s for s in steps if s.role == row["role"]]
            assert row["calls"] == len(matching)
            assert row["total_tokens"] == sum(s.usage.tokens_in + s.usage.tokens_out for s in matching)
        reviewers = [r for r in data["agents"] if svc.cfg.agents[r["role"]].kind == "reviewer"]
        assert data["reviewers"]["total_tokens"] == sum(r["total_tokens"] for r in reviewers)
        assert len({r["project_id"] for r in svc.store.usage_entries() if r["source"] == "run"}) == 2


@pytest.mark.parametrize("failure", ["paid", "unmetered", "timeout", "zero_usage"])
async def test_failed_and_zero_usage_calls(tmp_path: Path, failure: str):
    svc = services(tmp_path)
    run = Run(goal="hello", workspace=str(tmp_path))
    exc = NonRetryable("content_policy_refusal")
    if failure == "paid":
        exc.tokens_in, exc.tokens_out = 12, 3
        exc.usage_present = True
    if failure == "zero_usage":
        exc.usage_present = True
    chat = AsyncMock(side_effect=TimeoutError() if failure == "timeout" else exc)
    cfg = svc.cfg.model_copy(deep=True)
    cfg.retry.llm_call.num_retries = 0
    ctx = RunContext(run, lambda _: None, record_usage=UsageRecorder(svc.store, "turn", run.id, None))
    with pytest.raises(LlmError):
        await StructuredCaller(cfg, chat).call(
            "root", AgentInput(run_id=run.id, iteration=0, goal="hello"), RootTurn, ctx
        )
    total = summarize(svc.store, svc.cfg.agents).total
    assert total.calls == int(failure in {"paid", "zero_usage"})
    assert total.unmetered_calls == int(failure in {"unmetered", "timeout"})
    assert total.total_tokens == (15 if failure == "paid" else 0)


async def test_json_repair_and_retry_each_count_once(tmp_path: Path):
    svc = services(tmp_path)
    error = Retryable("rate_limit_429")
    error.tokens_in, error.tokens_out = 2, 1
    chat = AsyncMock(
        side_effect=[
            error,
            Completion("invalid json", 10, 5),
            Completion(RootTurn(intent="answer", reply="ok").model_dump_json(), 20, 8),
        ]
    )
    cfg = svc.cfg.model_copy(deep=True)
    cfg.retry.llm_call.backoff_base_s = 0
    run = Run(goal="hello", workspace=str(tmp_path))
    ctx = RunContext(run, lambda _: None, record_usage=UsageRecorder(svc.store, "turn", run.id, None))
    await StructuredCaller(cfg, chat).call("root", AgentInput(run_id=run.id, iteration=0, goal="hello"), RootTurn, ctx)
    summary = summarize(svc.store, cfg.agents)
    assert summary.total.calls == 3
    assert summary.total.total_tokens == 46


def test_ledger_rolls_back_with_usage_transaction(tmp_path: Path):
    svc = services(tmp_path)
    with pytest.raises(RuntimeError), svc.store.transaction():
        UsageRecorder(svc.store, "turn", "ref", None)(
            Usage(tokens_in=1, tokens_out=2).for_call("root", "fake", "fake"))
        raise RuntimeError("rollback")
    assert svc.store.usage_entries() == []


def test_project_planning_is_accounted(tmp_path: Path):
    svc = services(tmp_path)
    ws = seed_demo_workspace(tmp_path / "planned")
    with TestClient(create_app(svc)) as client:
        response = client.post(
            "/projects", json={"name": "planned", "goal": "fix add", "workspace": str(ws), "runtime": "fake"}
        )
        assert response.status_code == 200, response.text
        usage = client.get("/monitor/usage").json()
    planner = next(r for r in usage["agents"] if r["role"] == "project-planner")
    assert planner["calls"] == 1
    assert planner["tokens_in"] == svc.store.records("planning")[0]["tokens_in"] == 100
    assert svc.store.usage_entries()[0]["source"] == "planning"


async def test_native_search_records_usage_and_unmetered_failure(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace

    from agentlab.adapters.runtime.search import native_search

    svc = services(tmp_path)
    run = Run(goal="search", workspace=str(tmp_path))
    response = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=7, output_tokens=3),
        output_text="result",
        model_dump=lambda **_: {"output": [{"type": "web_search_call"}]},
    )
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.responses.create.side_effect = [response, RuntimeError("connection failed")]
    monkeypatch.setattr("agentlab.adapters.runtime.search.openai.AsyncOpenAI", lambda **_: client)
    svc.gateway = lambda: ("http://example.test", "test-key")
    ctx = RunContext(run, lambda _: None, record_usage=UsageRecorder(svc.store, "turn", run.id, None))
    await native_search(svc, svc.cfg, "query", ctx)
    with pytest.raises(RuntimeError):
        await native_search(svc, svc.cfg, "query", ctx)
    summary = summarize(svc.store, svc.cfg.agents).total
    assert summary.calls == summary.unmetered_calls == 1
    assert summary.total_tokens == 10
    assert summary.cost_cents >= svc.cfg.budget.ask.web_search_cents


def test_summary_reads_aggregates_only_and_nested_rollback_is_exact(tmp_path: Path, monkeypatch):
    from agentlab.core.schemas import Usage

    svc = services(tmp_path)
    account = UsageRecorder(svc.store, 'turn', 'ref', None)
    account(Usage(tokens_in=7).for_call('root', 'a', 'model', 'one'))
    with pytest.raises(RuntimeError), svc.store.transaction():
        account(Usage(tokens_in=3).for_call('root', 'b', 'other', 'two'))
        with svc.store.transaction():
            account(Usage(tokens_out=9).for_call('coder', 'b', 'other', 'three'))
        raise RuntimeError('rollback outer')
    assert len(svc.store.usage_entries()) == 1
    monkeypatch.setattr(svc.store, 'usage_entries', lambda: pytest.fail('summary must not scan the ledger'))
    total = summarize(svc.store, svc.cfg.agents).total
    assert (total.calls, total.tokens_in, total.tokens_out, total.models) == (1, 7, 0, ['model'])


def test_memory_transactions_do_not_copy_old_ledger_rows(tmp_path: Path):
    svc = services(tmp_path)
    class NoCopy:
        enabled = False
        def __deepcopy__(self, memo):
            if self.enabled:
                raise AssertionError('transaction copied historical ledger')
            return self
    sentinel = NoCopy()
    svc.store.append_usage({'id': 'old', 'source': 'turn', 'ref_id': 'old', 'project_id': None,
        'role': 'root', 'model_alias': 'a', 'model': 'model',
        'tokens_in': 1, 'tokens_out': 0, 'cost_cents': 0, 'metered': True, 'extra': sentinel})
    sentinel.enabled = True
    with svc.store.transaction():
        svc.store.put_record('test', 'key', {'value': 1})


async def test_search_paid_usage_survives_response_save_failure(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace

    from agentlab.adapters.runtime.search import native_search
    from agentlab.core.budget import BudgetGuard

    svc = services(tmp_path)
    run = Run(goal='search', workspace=str(tmp_path))
    response = SimpleNamespace(usage=SimpleNamespace(input_tokens=70, output_tokens=30), output_text='result',
        model_dump=lambda **_: {'output': [{'type': 'web_search_call'}]})
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.responses.create.return_value = response
    monkeypatch.setattr('agentlab.adapters.runtime.search.openai.AsyncOpenAI', lambda **_: client)
    svc.gateway = lambda: ('http://example.test', 'test-key')
    guard = BudgetGuard(run, 0.8, lambda _: None)
    def fail_save(identifier, payload):
        raise OSError('response save failed')
    ctx = RunContext(run, lambda _: None,
        record_usage=UsageRecorder(svc.store, 'turn', run.id, None, guard.record),
        attempt_started=lambda _: 'search-attempt', attempt_finished=fail_save,
        usage_transaction=svc.store.transaction)
    with pytest.raises(OSError, match='response save failed'):
        await native_search(svc, svc.cfg, 'query', ctx)
    total = summarize(svc.store, svc.cfg.agents).total
    assert total.calls == 1 and total.unmetered_calls == 0
    assert total.tokens_in == 70 and total.tokens_out == 30
    assert total.cost_cents == run.cost_cents
    assert total.cost_cents >= svc.cfg.budget.ask.web_search_cents


def test_recovery_is_idempotent_and_does_not_classify_live_calls(tmp_path: Path):
    from agentlab.core.monitor import recover_interrupted_calls, recover_run_calls

    svc = services(tmp_path)
    run = Run(goal='interrupted', workspace=str(tmp_path))
    svc.store.create_run(run)
    svc.store.put_record('attempt', 'lost', {'id': 'lost', 'run_id': run.id, 'role': 'coder',
        'alias': 'a', 'model': 'model', 'status': 'in_flight'})
    with svc.store.lock_run(run.id):
        recover_interrupted_calls(svc.store)
    assert not svc.store.usage_entries()
    recover_interrupted_calls(svc.store)
    recover_run_calls(svc.store, run.id)
    recover_interrupted_calls(svc.store)
    total = summarize(svc.store, svc.cfg.agents).total
    assert total.unmetered_calls == 1 and total.calls == 0


def test_accounting_replays_do_not_charge_budget_twice(tmp_path: Path):
    from agentlab.core.schemas import Usage

    svc = services(tmp_path)
    charges = []
    record = UsageRecorder(svc.store, 'turn', 'ref', None, charges.append)
    paid = Usage(tokens_in=7, tokens_out=3, cost_cents=0.5).for_call('root', 'a', 'model', 'same-call')
    record(paid)
    record(paid)
    assert len(charges) == 1
    assert summarize(svc.store, svc.cfg.agents).total.calls == 1
