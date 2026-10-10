from unittest.mock import AsyncMock

import pytest

from agentlab.core.schemas import GateResult
from agentlab.evaluation.fixtures import InvalidFixture, changed_files, require_test_failure


@pytest.mark.parametrize("failed_at, passed", [("typecheck", False), ("lint", False), ("format", False), (None, True)])
async def test_invalid_baseline_is_a_fixture_error(tmp_path, failed_at, passed):
    gate = AsyncMock()
    gate.run.return_value = GateResult(language="python", mode="full", steps=[], passed=passed, failed_at=failed_at)
    with pytest.raises(InvalidFixture):
        await require_test_failure(gate, tmp_path)


async def test_baseline_fails_at_tests(tmp_path):
    gate = AsyncMock()
    gate.run.return_value = GateResult(language="python", mode="full", steps=[], passed=False, failed_at="test")
    assert (await require_test_failure(gate, tmp_path)).failed_at == "test"


def test_configuration_changes_and_added_or_deleted_files_are_detected():
    before = {"calc.py": b"wrong", "pyproject.toml": b"strict", "test_calc.py": b"tests"}
    after = {"calc.py": b"fixed", "pyproject.toml": b"ignore tests", "bypass.cfg": b"bypass"}
    assert changed_files(before, after) == ["bypass.cfg", "calc.py", "pyproject.toml", "test_calc.py"]


async def test_bad_fixture_is_reported_without_model_calls(tmp_path, monkeypatch):
    import json

    from agentlab.evaluation import baseline
    from tests.unit.test_project_experience import services

    svc = services(tmp_path)
    svc.runtime = lambda *args, **kwargs: AsyncMock()
    monkeypatch.setenv("AGENTLAB_DATA_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(baseline, "evaluation_workspace_root", lambda: tmp_path)
    monkeypatch.setattr(baseline, "build_services", lambda _: svc)
    from types import SimpleNamespace

    gate = SimpleNamespace(
        cfg=svc.cfg.gates["python"],
        run=AsyncMock(
            return_value=GateResult(language="python", mode="full", steps=[], passed=False, failed_at="typecheck")
        ),
    )
    monkeypatch.setattr("agentlab.adapters.gates.config_gate.resolve_gate", lambda *args: gate)
    fixture = tmp_path / "tasks" / "broken"
    fixture.mkdir(parents=True)
    (fixture / "test_calc.py").write_text("def test_missing_type():\n    pass\n")
    (fixture / "calc.py").write_text("def add(a, b):\n    return a-b\n")
    manifest = tmp_path / "baseline.json"
    manifest.write_text(
        json.dumps({"tasks": [{"id": "broken", "goal": "fix", "solution": "ignored"}], "conversations": []})
    )
    report = await baseline.evaluate(manifest)
    card = report["scorecards"][0]
    assert card["failure_kind"] == "fixture"
    assert card["baseline_gate"]["failed_at"] == "typecheck"
    assert not svc.store.list_runs()
    assert (tmp_path / "state" / "eval-results").exists()


async def test_task_timeout_records_state_last_event_and_continues(tmp_path, monkeypatch):
    import asyncio
    import json
    from pathlib import Path

    from agentlab.core.loop.driver import Driver
    from agentlab.core.schemas import EventType, RunStatus
    from agentlab.evaluation import baseline
    from tests.unit.test_project_experience import services

    svc = services(tmp_path)
    monkeypatch.setenv("AGENTLAB_DATA_DIR", str(tmp_path / "results"))
    monkeypatch.setattr(baseline, "evaluation_workspace_root", lambda: tmp_path)
    monkeypatch.setattr(baseline, "build_services", lambda _: svc)
    monkeypatch.setattr(
        baseline,
        "require_test_failure",
        AsyncMock(return_value=GateResult(language="python", mode="full", steps=[], passed=False, failed_at="test")),
    )
    cancelled = []

    async def stalled_run(self, run_id):
        run = self.store.get_run(run_id)
        run.status = RunStatus.CODING
        self.store.save_run(run)
        self._emit(run, EventType.STEP_STARTED, actor="coder", role="coder")
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(run_id)

    monkeypatch.setattr(Driver, "run", stalled_run)
    fixture = tmp_path / "tasks"
    for name in ["first", "second"]:
        p = fixture / name
        p.mkdir(parents=True)
        (p / "calc.py").write_text("value = 1\n")
        (p / "test_calc.py").write_text("def test_value() -> None:\n    assert False\n")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "tasks": [{"id": name, "goal": "Fix value", "solution": "value = 2\n"} for name in ["first", "second"]],
                "conversations": [],
            }
        )
    )
    report = await baseline.evaluate(manifest, task_timeout_s=0.3)
    assert len(cancelled) == 2
    assert not report["passed"]
    for card in report["scorecards"]:
        assert card["stopped_reason"] == card["failure_kind"] == "timeout"
        assert card["run_state"]["status"] == "CODING"
        assert card["last_event"]["type"] == "step.started"
        assert card["last_event"]["actor"] == "coder"
        persisted = json.loads((Path(report["results_dir"]) / (card["run_id"] + ".json")).read_text())
        assert persisted["run_state"] == card["run_state"]


async def test_conversation_timeout_is_scored_instead_of_aborting_eval(tmp_path, monkeypatch):
    import asyncio
    import json

    from agentlab.evaluation import baseline
    from tests.unit.test_project_experience import services

    svc = services(tmp_path)
    monkeypatch.setenv("AGENTLAB_DATA_DIR", str(tmp_path / "results"))
    monkeypatch.setattr(baseline, "evaluation_workspace_root", lambda: tmp_path)
    monkeypatch.setattr(baseline, "build_services", lambda _: svc)

    async def stalled_answer(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(baseline.SessionService, "answer", stalled_answer)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "tasks": [],
                "conversations": [{"id": "root-timeout", "intent": "answer", "reply": "Hello", "text": "Hello"}],
            }
        )
    )
    report = await baseline.evaluate(manifest, task_timeout_s=0.1)
    assert report["scorecards"][0]["stopped_reason"] == "timeout"
    assert report["scorecards"][0]["run_state"] is None
