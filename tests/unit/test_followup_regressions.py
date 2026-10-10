from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agentlab.adapters.runtime.raw import OpenAICompatChat, RawRuntime
from agentlab.adapters.workspace import GitWorkspace, WorkspaceEscape
from agentlab.core.budget import BudgetExceeded
from agentlab.core.llm.retry import NonRetryable, ParallelFailure
from agentlab.core.loop.arbiter import arbitrate
from agentlab.core.schemas import AgentInput, AgentResult, ArbiterAction, FileEdit, RunStatus, Usage, Verdict
from tests.conftest import finding, verdict
from tests.unit.test_driver import make_driver


@pytest.mark.parametrize("path", [".ENV", ".Env.local", ".GIT/config", ".AgentLab/config", "ID_RSA", "cert.KEY"])
def test_case_insensitive_reserved_paths(tmp_path, path):  # type: ignore[no-untyped-def]
    ws = GitWorkspace(tmp_path)
    (tmp_path / ".env").write_text("A=1")
    with pytest.raises(WorkspaceEscape):
        ws.apply_edits([FileEdit(path=path, content="A=pwned")])
    assert (tmp_path / ".env").read_text() == "A=1"


async def test_normal_source_names_remain_editable_and_reviewable(tmp_path):  # type: ignore[no-untyped-def]
    ws = GitWorkspace(tmp_path)
    await ws.ensure_repo()
    ws.begin_run()
    paths = ["src/private_api.py", "tests/test_secret_rotation.py", "keyboard.keymap"]
    ws.apply_edits([FileEdit(path=p, content="value = 1\n") for p in paths])
    diff = await ws.diff()
    files = await ws.context_files()
    assert all(p in diff for p in paths)
    assert all(p in files for p in paths)


@pytest.mark.parametrize("content", ["x" * 100_001, "sk-" + "a" * 25, "\0binary"],
                         ids=["oversize", "secret", "binary"])
async def test_filtered_current_file_is_not_reported_as_deleted(tmp_path, content):  # type: ignore[no-untyped-def]
    (tmp_path / "file.py").write_text("value = 1\n")
    ws = GitWorkspace(tmp_path)
    await ws.ensure_repo()
    ws.begin_run()
    (tmp_path / "file.py").write_text(content)
    diff = await ws.diff()
    assert "file.py" in diff and "changed (" in diff
    assert "deleted file mode" not in diff
    if content.startswith("sk-"):
        assert content not in diff


def test_opposing_soft_comments_do_not_block_signoff():
    a = finding(sev="nit").model_copy(update={"subject": "add-lock", "stance": "require"})
    b = finding(sev="minor").model_copy(update={"subject": "add-lock", "stance": "forbid"})
    assert arbitrate([verdict("a", a), verdict("b", b)], .7).action == ArbiterAction.SIGNOFF


async def test_paid_plan_is_saved_before_next_budget_pause(cfg, tmp_path):  # type: ignore[no-untyped-def]
    driver = await make_driver(cfg, tmp_path)
    base = driver.runtime.run_agent
    calls = []
    async def costly(role, inp, output_type, ctx):  # type: ignore[no-untyped-def]
        calls.append(role)
        result = await base(role, inp, output_type, ctx)
        result.usage = Usage(cost_cents=50)
        return result
    driver.runtime.run_agent = costly
    run = await driver.run(driver.create("fix add", budget_cents=40).id)
    assert run.status == RunStatus.WAITING_HUMAN and run.paused_reason == "budget_exceeded"
    assert driver.store.artifacts(run.id, "plan")
    assert calls == ["planner"]
    approval = driver.store.pending_approval(run.id)
    assert approval.on_approve == RunStatus.CODING
    assert approval.payload["required_budget_cents"] > run.cost_cents
    driver.decide(run.id, "approve", budget_cents=approval.payload["required_budget_cents"])
    await driver.run(run.id)
    assert calls == ["planner", "coder"]


async def test_partial_paid_reviews_are_reused_and_required_covers_remaining_batch(cfg, tmp_path):  # type: ignore[no-untyped-def]
    driver = await make_driver(cfg, tmp_path)
    run = driver.create("fix add", budget_cents=200)
    run.status = RunStatus.REVIEWING
    roles = cfg.reviewer_roles
    calls = []
    def result(role):  # type: ignore[no-untyped-def]
        return AgentResult(role=role, output=Verdict(reviewer_id=role, verdict="APPROVE"),
                           alias="strong", model="test", usage=Usage(cost_cents=1))
    async def partial(inputs, output_type, ctx):  # type: ignore[no-untyped-def]
        calls.extend(inputs)
        raise ParallelFailure(BudgetExceeded("test"), [result(roles[0])])
    driver.runtime.run_parallel = partial
    inp = AgentInput(run_id=run.id, iteration=1, goal=run.goal)
    with pytest.raises(BudgetExceeded) as error:
        await driver._agents(run, roles, inp, Verdict)
    required = error.value.required_budget_cents
    assert required > run.cost_cents
    async def remaining(inputs, output_type, ctx):  # type: ignore[no-untyped-def]
        assert roles[0] not in inputs
        return [result(r) for r in inputs]
    driver.runtime.run_parallel = remaining
    run.budget_cents = required
    results = await driver._agents(run, roles, inp, Verdict)
    assert [r.role for r in results] == roles
    assert len(driver.store.steps(run.id)) == 3
    assert run.cost_cents == 3


async def test_parallel_cancellation_cannot_become_partial_signoff():
    runtime = object.__new__(RawRuntime)
    async def cancelled(*args):  # type: ignore[no-untyped-def]
        raise asyncio.CancelledError()
    runtime.run_agent = cancelled
    with pytest.raises(ParallelFailure) as failure:
        await runtime.run_parallel({"a": AgentInput(run_id="r", iteration=1, goal="g")}, Verdict, None)
    assert failure.value.cause.kind == "agent_cancelled"


@pytest.mark.parametrize("parameter", ["max_tokens", "max_completion_tokens"])
async def test_output_limit_parameter_and_truncation_preserve_usage(parameter):  # type: ignore[no-untyped-def]
    chat = OpenAICompatChat("https://example.invalid/v1", "test", 1)
    create = AsyncMock(return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"broken":', refusal=None), finish_reason="length")],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=16000)))
    chat._client.chat.completions.create = create
    with pytest.raises(NonRetryable) as error:
        await chat(model="test", system="s", messages=[], temperature=0, schema={},
                   max_output_tokens=16000, output_token_parameter=parameter)
    assert create.call_args.kwargs[parameter] == 16000
    assert error.value.kind == "output_truncated" and error.value.tokens_out == 16000
    await chat._client.close()


async def test_project_paid_plan_survives_actual_overrun(cfg, tmp_path):  # type: ignore[no-untyped-def]
    from agentlab.bootstrap import build_services
    from agentlab.core.project import PhasePlan, ProjectPlan
    from agentlab.settings import Settings
    from tests.conftest import CONFIG_DIR
    svc = build_services(Settings(config_dir=CONFIG_DIR, data_dir=tmp_path, _env_file=None))
    project = svc.projects.create("p", "g", str(tmp_path), publish=False)
    runtime = SimpleNamespace(run_agent=AsyncMock(return_value=AgentResult(
        role="project-planner", output=ProjectPlan(phases=[PhasePlan(title="phase", steps=["step"])]), alias="root", model="test", usage=Usage(cost_cents=2))))
    planned = await svc.projects.plan(project, runtime, svc.knowledge, budget_cents=1)
    assert planned is project
    assert svc.projects.planning_attempts[-1]["budget_overrun"] is True


async def test_conflict_approval_requires_actionable_feedback(cfg, tmp_path):  # type: ignore[no-untyped-def]
    driver = await make_driver(cfg, tmp_path)
    run = driver.create("fix add")
    driver._escalate(run, "reviewer_conflict", {})
    with pytest.raises(ValueError, match="feedback"):
        driver.decide(run.id, "approve")
    driver.decide(run.id, "approve", feedback="Use validation before writing the file")
    assert driver.store.artifacts(run.id, "feedback")


async def test_snapshot_git_has_timeout_and_diff_runs_off_event_loop(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    import threading

    import agentlab.adapters.workspace as module
    ws = GitWorkspace(tmp_path)
    loop_thread = threading.get_ident()
    seen = []
    def git(*args, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(threading.get_ident())
        assert kwargs["timeout"] == 30
        return SimpleNamespace(stdout=b"")
    monkeypatch.setattr(module.subprocess, "run", git)
    assert await ws.diff() == ""
    assert seen and seen[0] != loop_thread


async def test_review_batch_preflight_requires_all_three_requests(cfg, tmp_path):  # type: ignore[no-untyped-def]
    driver = await make_driver(cfg, tmp_path)
    run = driver.create("fix add", budget_cents=40)
    run.status = RunStatus.REVIEWING
    inp = AgentInput(run_id=run.id, iteration=1, goal=run.goal)
    parallel = AsyncMock(return_value=[AgentResult(
        role=r, output=Verdict(reviewer_id=r, verdict="APPROVE"), alias="strong", model="test", usage=Usage())
        for r in cfg.reviewer_roles])
    driver.runtime.run_parallel = parallel
    with pytest.raises(BudgetExceeded) as error:
        await driver._agents(run, cfg.reviewer_roles, inp, Verdict)
    parallel.assert_not_called()
    run.budget_cents = error.value.required_budget_cents
    assert len(await driver._agents(run, cfg.reviewer_roles, inp, Verdict)) == 3
    parallel.assert_awaited_once()


def test_fixed_inverse_actions_are_normalized_to_the_same_requirement():
    a = finding().model_copy(update={"subject": "add-lock", "stance": "require"})
    b = finding().model_copy(update={"subject": "remove-lock", "stance": "require"})
    assert arbitrate([verdict("a", a), verdict("b", b)], .7).reason == "reviewer_conflict"
