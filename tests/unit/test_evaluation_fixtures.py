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
