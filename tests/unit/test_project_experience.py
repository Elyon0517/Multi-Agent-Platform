from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentlab.api.app import create_app
from agentlab.bootstrap import build_services
from agentlab.core.project_config import Binding, Dispatch, ProjectSettings, project_config, worker_roles
from agentlab.demo import seed_demo_workspace
from agentlab.settings import Settings
from tests.conftest import CONFIG_DIR


def services(tmp: Path):
    return build_services(Settings(store_backend="memory", config_dir=CONFIG_DIR, data_dir=tmp,
                                  env_file=tmp / ".env", runtime="fake", sandbox="local", _env_file=None))


def test_manual_routing_has_exact_bindings_and_no_fallback(tmp_path: Path) -> None:
    svc = services(tmp_path)
    bindings = {r: Binding(alias="strong-alt", task=f"Specific task for {r}") for r in worker_roles(svc.cfg)}
    settings = ProjectSettings(mode="manual", root_alias="strong", bindings=bindings, budget_cents=321, max_iter=3)
    cfg = project_config(svc.cfg, settings)
    assert cfg.budget.default_run_budget_cents == 321
    assert cfg.budget.loop.max_iter == 3
    assert cfg.model_policy.roles["project-planner"].primary == "strong"
    assert all(cfg.model_policy.roles[r].primary == "strong-alt" and not cfg.model_policy.roles[r].fallback
               for r in bindings)
    with pytest.raises(ValueError, match="every worker"):
        project_config(svc.cfg, settings.model_copy(update={"bindings": {}}))
    with pytest.raises(ValueError, match="unavailable"):
        Dispatch(assignments={r: Binding(alias="unknown", task="task") for r in bindings}).validate_for(svc.cfg, settings)


def test_private_documents_threads_and_workspace_isolation(tmp_path: Path) -> None:
    svc = services(tmp_path)
    with TestClient(create_app(svc)) as client:
        projects = []
        for name in ("one", "two"):
            ws = seed_demo_workspace(tmp_path / name)
            response = client.post("/projects", json={"name": name, "goal": "fix add", "workspace": str(ws),
                                                        "runtime": "fake", "settings": ProjectSettings().model_dump()})
            assert response.status_code == 200, response.text
            projects.append(response.json())
        a, b = projects
        assert client.post("/projects", json={"name": "overlap", "goal": "goal", "workspace": a["workspace"],
                                                "runtime": "fake"}).status_code == 409
        for project, contents in ((a, "alpha private apples"), (b, "beta private apples")):
            assert client.post(f'/knowledge?project_id={project["id"]}', files={"file": ("same.md", contents)}).status_code == 200
        assert client.get("/knowledge").json() == []
        hits = client.post("/memory/search", json={"query": "apples", "project_id": a["id"]}).json()
        assert [h["item"]["text"] for h in hits] == ["alpha private apples"]
        assert client.delete(f'/knowledge/same.md?project_id={a["id"]}').json()["deleted"] == 1
        assert len(client.get(f'/knowledge?project_id={b["id"]}').json()) == 1
        assert client.post("/memory", json={"scope": "agent", "role": "coder", "text": "secret"}).status_code == 422
        assert client.get("/knowledge?project_id=missing").status_code == 404
        thread = client.post(f'/projects/{a["id"]}/threads', json={"title": "Discussion"}).json()
        assert client.get(f'/projects/{b["id"]}/threads').json() == []
        assert client.post("/runs", json={"goal": "fix", "project_id": b["id"], "thread_id": thread["id"]}).status_code == 404
        assert not svc.store.list_runs()
        assert client.put(f'/projects/{a["id"]}/settings', json={"mode": "manual"}).status_code == 422


async def test_auto_dispatch_is_checkpointed_and_manual_settings_frozen(tmp_path: Path) -> None:
    svc = services(tmp_path)
    ws = seed_demo_workspace(tmp_path / "auto")
    project = svc.projects.create("auto", "fix add", str(ws))
    project.settings = ProjectSettings()
    svc.projects.save(project)
    driver = svc.driver(ws, "fake", "python", project.id)
    await driver.workspace.ensure_repo()
    run = await driver.create_async("fix add", project_id=project.id)
    observer = svc.restore_driver(run.id)
    await driver._planning(run)
    observer._reload_checkpoint(run.id)
    assert observer.cfg.model_policy.roles["arch-reviewer"].primary == "strong"
    assert len(svc.store.artifacts(run.id, "dispatch")) == 1
    assert svc.store.steps(run.id)[0].role == "supervisor"
    checkpoint = svc.store.checkpoint(run.id)
    assert checkpoint is not None
    assert driver.recovery_options["assignments"].keys() == worker_roles(svc.cfg)
    project.settings = ProjectSettings(retrieval="off", budget_cents=999)
    svc.projects.save(project)
    restored = svc.restore_driver(run.id)
    assert restored.recovery_options["project_settings"]["retrieval"] == "keyword"
    assert restored.cfg.budget.default_run_budget_cents == 500
    assert restored.recovery_options["assignments"] == driver.recovery_options["assignments"]
    driver.workspace.close()


async def test_workspace_rejects_a_second_unfinished_run(tmp_path: Path) -> None:
    from agentlab.core.ports import RunBusy
    svc = services(tmp_path)
    ws = seed_demo_workspace(tmp_path / "exclusive")
    first = svc.driver(ws, "fake", "python")
    await first.workspace.ensure_repo()
    run = await first.create_async("first")
    second = svc.driver(ws, "fake", "python")
    with pytest.raises(RunBusy, match="unfinished run"):
        await second.create_async("second")
    with pytest.raises(RunBusy, match="unfinished run"):
        second.create("second via CLI")
    assert len(svc.store.list_runs()) == 1
    assert svc.store.get_run(run.id).goal == "first"
    first.workspace.close()
    second.workspace.close()


def test_project_yaml_profile_is_validated_and_round_trips(tmp_path: Path) -> None:
    svc = services(tmp_path)
    project = svc.projects.create("profile", "goal", str(tmp_path / "repo"))
    with TestClient(create_app(svc)) as client:
        profile = client.get(f"/projects/{project.id}/profile").text
        assert "root_alias: root" in profile
        response = client.put(f"/projects/{project.id}/profile", json={"yaml_text": profile.replace("keyword", "off")})
        assert response.status_code == 200 and response.json()["settings"]["retrieval"] == "off"
        assert client.put(f"/projects/{project.id}/profile", json={"yaml_text": "unknown: value"}).status_code == 422
        assert "retrieval: 'off'" in client.get(f"/projects/{project.id}/profile").text


async def test_document_removal_does_not_retire_a_same_source_note(tmp_path: Path) -> None:
    from agentlab.core.memory.store import PROJECT
    svc = services(tmp_path)
    note = await svc.knowledge.note("p", PROJECT, "preserve this note")
    note.source = "manual.md"
    await svc.knowledge.ingest("manual.md", b"document", "p")
    assert note.valid_to is None
    assert svc.knowledge.delete("manual.md", "p") == 1
    assert svc.knowledge.memory.items_in(PROJECT, "p") == [note]


async def test_p2_legacy_paid_input_cache_remains_reusable(tmp_path: Path) -> None:
    import hashlib

    from agentlab.core.schemas import Plan
    svc = services(tmp_path)
    driver = svc.driver(seed_demo_workspace(tmp_path / "legacy"), "fake", "python")
    await driver.workspace.ensure_repo()
    run = await driver.create_async("fix add")
    inp = driver._input(run)
    paid = await driver._agent(run, "planner", inp, Plan)
    cost = run.cost_cents
    legacy_hash = hashlib.sha256(inp.model_dump_json(exclude={"context"}).encode()).hexdigest()
    key, inputs = next(iter(driver._agent_inputs.items()))
    driver._agent_inputs = {(*key[:3], legacy_hash): inputs}
    result_key = next(iter(driver._completed_agents))
    driver._completed_agents = {(*result_key[:3], "planner" + legacy_hash): paid}
    driver._checkpoint(run)
    restored = svc.restore_driver(run.id)
    class NoCalls:
        async def run_agent(self, *args):
            raise AssertionError("legacy paid result was billed again")
    restored.runtime = NoCalls()
    result = await restored._agent(run, "planner", inp, Plan)
    assert result.output == paid.output and run.cost_cents == cost
    driver.workspace.close()


def test_project_step_run_gets_a_conversation_and_terminal_message(tmp_path: Path) -> None:
    import time
    svc = services(tmp_path)
    project = svc.projects.create("conversation", "fix add", str(seed_demo_workspace(tmp_path / "chat")))
    with TestClient(create_app(svc)) as client:
        response = client.post("/runs", json={"goal": "fix add", "project_id": project.id, "runtime": "fake"})
        assert response.status_code == 200, response.text
        run = response.json()
        assert run["thread_id"]
        assert client.post("/runs", json={"goal": "second", "project_id": project.id, "runtime": "fake"}).status_code == 409
        threads = client.get(f"/projects/{project.id}/threads").json()
        assert len(threads) == 1 and threads[0]["messages"][0]["run_id"] == run["id"]
        for _ in range(100):
            detail = client.get(f'/runs/{run["id"]}').json()
            if detail["run"]["status"] == "WAITING_HUMAN":
                break
            time.sleep(0.1)
        assert detail["pending_approval"]["reason"] == "signoff"
        assert client.post(f'/runs/{run["id"]}/decision', json={"decision": "approve"}).status_code == 200
        for _ in range(100):
            messages = client.get(f"/projects/{project.id}/threads").json()[0]["messages"]
            if len(messages) == 2:
                break
            time.sleep(0.05)
        assert messages[1]["author"] == "system" and "DONE" in messages[1]["text"]


async def test_invalid_dispatch_requires_feedback_instead_of_replaying_paid_invalid_output(tmp_path: Path) -> None:
    svc = services(tmp_path)
    workspace = seed_demo_workspace(tmp_path / "invalid-dispatch")
    project = svc.projects.create("auto", "fix add", str(workspace))
    project.settings = ProjectSettings()
    svc.projects.save(project)
    driver = svc.driver(workspace, "fake", "python", project.id)
    await driver.workspace.ensure_repo()
    run = await driver.create_async("fix add", project_id=project.id)
    original = driver.runtime
    class BadDispatch:
        async def run_agent(self, role, inp, out, ctx):
            result = await original.run_agent(role, inp, out, ctx)
            result.output.assignments["coder"].alias = "not-allowed"
            return result
    driver.runtime = BadDispatch()
    run = await driver.run(run.id)
    assert run.paused_reason == "dispatch_invalid" and run.cost_cents > 0
    assert not driver.recovery_options.get("assignments")
    with pytest.raises(ValueError, match="reject with feedback"):
        driver.decide(run.id, "approve")
    with pytest.raises(ValueError, match="reject with feedback"):
        driver.decide(run.id, "reject")
    driver.decide(run.id, "reject", feedback="Use only the supplied model aliases")
    await driver._planning(svc.store.get_run(run.id))
    assert driver.recovery_options["assignments"]["coder"]["alias"] == "strong"
    driver.workspace.close()
