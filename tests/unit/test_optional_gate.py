from pathlib import Path

from fastapi.testclient import TestClient

from agentlab.adapters.gates.config_gate import ConfigGate, resolve_gate
from agentlab.adapters.sandbox.local import LocalSandbox
from agentlab.api.app import create_app
from agentlab.core.schemas import RunStatus
from agentlab.demo import demo_gate_cfg, seed_demo_workspace
from tests.unit.test_memory_project import _svc


async def test_no_gate_review_rework_signoff_and_restore(tmp_path):
    svc = _svc(tmp_path)
    workspace = seed_demo_workspace(tmp_path / "go-workspace")
    driver = svc.driver(workspace, "fake", "go")
    assert driver.gate is None
    await driver.workspace.ensure_repo()
    run = await driver.create_async("Fix public add API")
    run = await driver.run(run.id)
    assert run.status == RunStatus.WAITING_HUMAN and run.paused_reason == "signoff"
    approval = svc.store.pending_approval(run.id)
    assert approval.payload["automated_checks"] == "not_run"
    assert not any(e.type == "gate.finished" or e.payload.get("dst") == "GATING" for e in svc.store.events(run.id))
    assert len(svc.store.iterations(run.id)) == 2  # Reviewer still sends missing docs back to Coder.
    assert all(i.gate_result is None for i in svc.store.iterations(run.id))
    assert all(inp.gate is None for role, inp in driver.runtime.inputs if "reviewer" in role)
    with TestClient(create_app(svc)) as client:
        assert client.get(f"/runs/{run.id}").json()["gate_reports"] == []
    restored = svc.restore_driver(run.id)
    assert restored.gate is None
    restored.decide(run.id, "approve")
    assert (await restored.run(run.id)).status == RunStatus.DONE


def test_gate_resolution_preserves_python_and_accepts_other_languages(tmp_path):
    gate = ConfigGate(demo_gate_cfg(), LocalSandbox())
    assert resolve_gate([gate], tmp_path) is None
    for language in ["go", "rust", "typescript", "java", "cpp"]:
        assert resolve_gate([gate], tmp_path, language) is None
    (tmp_path / "pyproject.toml").write_text("")
    assert resolve_gate([gate], tmp_path) is gate
    assert resolve_gate([gate], tmp_path, "python") is gate


async def test_gate_reports_include_failures_and_full_signoff(tmp_path):
    svc = _svc(tmp_path)
    workspace = seed_demo_workspace(tmp_path / "python")
    driver = svc.driver(workspace, "fake", "python")
    await driver.workspace.ensure_repo()
    run = await driver.run((await driver.create_async("Fix add")).id)
    assert svc.store.pending_approval(run.id).payload["automated_checks"] == "passed"
    with TestClient(create_app(svc)) as client:
        reports = client.get(f"/runs/{run.id}").json()["gate_reports"]
        assert any(not report["passed"] for report in reports)
        assert any(d["file"] == "test_calc.py" and d["line"] is not None
                   for report in reports for step in report["steps"] for d in step["diagnostics"])
        assert reports[-1]["mode"] == "full" and reports[-1]["passed"]
        events = client.get(f"/runs/{run.id}/events/history").json()
        assert events[-1]["seq"] == len(svc.store.events(run.id))


async def test_memory_eval_scores_semantic_failures_and_marks_fake_blind_spots(tmp_path, monkeypatch):
    import json

    from agentlab.evaluation.memory import evaluate_memory_case
    svc = _svc(tmp_path)
    cases = json.loads((Path(__file__).parents[2] / "evals/memory.json").read_text())["memory_cases"]
    for case in cases:
        card = await evaluate_memory_case(svc, case, "fake", 10)
        assert card["passed"] and card["blind_spot_count"] == 1
        assert not card["semantic_model_evaluated"]
    # A schema-valid, empty model response must fail the semantic rubric.
    from agentlab.adapters.runtime.fake import FakeRuntime
    from agentlab.core.memory.summarizer import MemoryOps
    monkeypatch.setattr(type(svc), "runtime", lambda *args: FakeRuntime({"summarizer": lambda inp: MemoryOps()}))
    failed = await evaluate_memory_case(svc, cases[1], "raw", 10)
    assert not failed["passed"]
    assert failed["categories"]["invocation"] and not failed["categories"]["preference_global"]


def test_go_project_api_auto_detects_no_gate_and_labels_signoff(tmp_path):
    import time

    svc = _svc(tmp_path)
    workspace = tmp_path / "go"
    workspace.mkdir()
    (workspace / "go.mod").write_text("module example.com/demo\n\ngo 1.22\n")
    (workspace / "main.go").write_text("package main\nfunc main() {}\n")
    with TestClient(create_app(svc)) as client:
        response = client.post("/runs", json={"goal": "Update public API docs", "workspace": str(workspace),
                                              "runtime": "fake"})
        assert response.status_code == 200, response.text
        identifier = response.json()["id"]
        for _ in range(100):
            detail = client.get(f"/runs/{identifier}").json()
            if detail["pending_approval"]:
                break
            time.sleep(0.01)
        assert detail["pending_approval"]["reason"] == "signoff"
        assert detail["pending_approval"]["payload"]["automated_checks"] == "not_run"
        assert not detail["gate_reports"]
