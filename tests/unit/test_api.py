from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from agentlab.api.app import create_app
from agentlab.bootstrap import build_services
from agentlab.settings import Settings
from tests.conftest import CONFIG_DIR


def test_run_lifecycle_over_http(tmp_path: Path) -> None:
    svc = build_services(Settings(config_dir=CONFIG_DIR, data_dir=tmp_path, runtime="fake", env_file=tmp_path / ".env"))
    with TestClient(create_app(svc)) as client:
        assert {r["role"] for r in client.get("/roster").json()} >= {"supervisor", "coder", "arbiter"}
        run = client.post("/runs", json={"goal": "fix add", "runtime": "fake", "language": "python"}).json()
        for _ in range(100):
            detail = client.get(f"/runs/{run['id']}").json()
            if detail["run"]["status"] == "WAITING_HUMAN":
                break
            time.sleep(0.1)
        assert detail["pending_approval"]["reason"] == "signoff"
        assert client.post(f"/runs/{run['id']}/decision", json={"decision": "approve"}).json()["status"] == "DONE"
        diff = next(a for a in detail["artifacts"] if a["kind"] == "diff")
        assert "calc.py" in client.get(f"/artifacts/{run['id']}/{diff['id']}").json()["content"]


def test_missing_gateway_is_a_clear_400(tmp_path: Path) -> None:
    svc = build_services(Settings(config_dir=CONFIG_DIR, data_dir=tmp_path, runtime="raw", env_file=tmp_path / ".env",
                                  llm_base_url=None, llm_api_key=None, _env_file=None))  # type: ignore[call-arg]
    with TestClient(create_app(svc)) as client:
        res = client.post("/runs", json={"goal": "x", "language": "python"})
        assert res.status_code == 400 and "AGENTLAB_LLM_BASE_URL" in res.json()["detail"]


def test_project_run_rejects_wrong_workspace_and_unknown_step(tmp_path: Path) -> None:
    svc = build_services(Settings(config_dir=CONFIG_DIR, data_dir=tmp_path, runtime="fake",
                                  env_file=tmp_path / ".env", _env_file=None))  # type: ignore[call-arg]
    project = svc.projects.create("p", "goal", str(tmp_path / "workspace"))
    with TestClient(create_app(svc)) as client:
        assert client.post("/runs", json={"goal": "x", "project_id": project.id,
                                           "workspace": str(tmp_path / "other")}).status_code == 422
        assert client.post("/runs", json={"goal": "x", "project_id": project.id,
                                           "step_id": "missing"}).status_code == 404
        assert client.post("/runs", json={"goal": "x", "project_id": "missing"}).status_code == 404
        assert not svc.store.list_runs()
