import json
from pathlib import Path

import pytest

from agentlab.adapters.runtime.fake import FakeRuntime
from agentlab.adapters.workspace import GitWorkspace
from agentlab.core.evidence import EvidenceContract, EvidenceRecord, evidence_status, validate_record
from agentlab.core.llm.tools import WorkerTools
from agentlab.core.schemas import CoderOutput, RunStatus
from agentlab.demo import demo_scripts, seed_demo_workspace
from tests.unit.test_memory_project import _svc


def contract():
    return EvidenceContract.model_validate({"requirements": [{"id": "one", "description": "Compare numbers",
        "claim_path": "answer.txt", "line_start": 1, "line_end": 1}], "source_paths": ["source.txt"]})


def record():
    return EvidenceRecord.model_validate({"id": "one", "claim": {"path": "answer.txt", "line_start": 1,
        "line_end": 1, "quote": "The amount is 123."}, "sources": [{"path": "source.txt", "line_start": 2,
        "line_end": 2, "quote": "The amount is 124."}], "verdict": "contradiction", "reason": "The numbers disagree.",
        "calculation": "124 - 123 = 1", "negative_claim": False, "searches": []})


def files(root):
    (root / "answer.txt").write_text("The amount is 123.\n")
    (root / "source.txt").write_text("Header\nThe amount is 124.\n")


async def test_quotes_paths_and_searches_are_checked_and_state_survives_recreation(tmp_path):
    files(tmp_path)
    ws = GitWorkspace(tmp_path)
    state = {"contract": contract().model_dump(), "records": {}, "searches": []}
    async def search(q):
        return {}
    tools = WorkerTools("coder", ["workspace_read", "workspace_search"], ws, None, search, evidence_state=state)
    assert evidence_status(state)["missing_count"] == 1
    r = record()
    r.sources[0].quote = "Invented quoted number"
    result = await tools.execute("evidence_record", {"record": r.model_dump_json()})
    assert "quote does not match" in result["detail"]
    assert state["records"] == {}
    r = record()
    r.negative_claim = True
    r.searches = [{"path": "source.txt", "query": "missing"}]
    result = await tools.execute("evidence_record", {"record": r.model_dump_json()})
    assert "not executed" in result["detail"]
    await tools.execute("workspace_search", r.searches[0])
    result = await tools.execute("evidence_record", {"record": r.model_dump_json()})
    assert result["missing_count"] == 0
    restored = json.loads(json.dumps(state))
    tools2 = WorkerTools("coder", ["workspace_read"], ws, None, search, evidence_state=restored)
    assert (await tools2.execute("evidence_status", {}))["recorded_count"] == 1
    r = record()
    r.claim.line_start = r.claim.line_end = 2
    with pytest.raises(ValueError, match="outside required"):
        validate_record(r, contract(), ws.source_text, [])
    r = record()
    r.sources[0].path = "answer.txt"
    with pytest.raises(ValueError, match="not in evidence contract"):
        validate_record(r, contract(), ws.source_text, [])
    no_grant = WorkerTools("coder", [], ws, None, search, evidence_state=state)
    with pytest.raises(ValueError, match="not granted"):
        await no_grant.execute("evidence_status", {})


async def test_revision_stays_in_same_run_preserves_limits_and_missing_evidence_blocks_done(tmp_path: Path):
    svc = _svc(tmp_path)
    root = seed_demo_workspace(tmp_path / "ws")
    files(root)
    driver = svc.driver(root, "fake", "python")
    scripts = demo_scripts()
    scripts["coder"] = lambda inp: CoderOutput(edits=[], report="Claimed completed report")
    driver.runtime = FakeRuntime(scripts)
    driver.runtime_factory = None
    await driver.workspace.ensure_repo()
    run = await driver.create_async("read-only evidence audit")
    run = await driver.run(run.id)
    assert run.status == RunStatus.DONE
    prior = run.model_dump()
    driver = svc.restore_driver(run.id)
    driver.runtime_factory = lambda: FakeRuntime(scripts)
    driver.revise_report(run.id, "Missing the paired quotations", contract())
    revised = svc.store.get_run(run.id)
    assert revised.status == RunStatus.CODING
    assert revised.max_iter == prior["max_iter"]
    assert revised.budget_cents == prior["budget_cents"]
    assert revised.budget_unlimited == prior["budget_unlimited"]
    with pytest.raises(ValueError, match="completed read-only"):
        driver.revise_report(run.id, "Duplicate revision", contract())
    run = await driver.run(run.id)
    assert run.status == RunStatus.WAITING_HUMAN
    approval = svc.store.pending_approval(run.id)
    assert approval.payload["evidence_status"]["missing_count"] == 1
    assert len(svc.store.artifacts(run.id, "report")) == 1  # old report retained, bad new one not accepted
    # Finish the missing record, then check that valid quotes still don't bypass semantic signoff.
    driver.recovery_options["evidence"]["records"] = {"one": record().model_dump()}
    driver._checkpoint(run)
    driver.decide(run.id, "reject", "Finish the evidence-backed report")
    run = await driver.run(run.id)
    assert run.status == RunStatus.WAITING_HUMAN
    approval = svc.store.pending_approval(run.id)
    assert approval.reason == "signoff"
    assert approval.payload["read_only_evidence"] is True
    assert len(svc.store.artifacts(run.id, "evidence")) == 1
    assert len(svc.store.list_runs()) == 1


async def test_capture_ids_avoid_retyping_and_remain_bound_to_source(tmp_path):
    files(tmp_path)
    ws = GitWorkspace(tmp_path)
    state = {"contract": contract().model_dump(), "records": {}, "searches": []}
    async def search(q):
        return {}
    tools = WorkerTools("coder", ["workspace_read"], ws, None, search, evidence_state=state)
    claim = await tools.execute("evidence_capture", {"path": "answer.txt", "line_start": 1,
        "line_end": 1, "char_start": 0, "char_count": 2000})
    source = await tools.execute("evidence_capture", {"path": "source.txt", "line_start": 2,
        "line_end": 2, "char_start": 0, "char_count": 2000})
    assert source["quote"] == "The amount is 124.\n"
    assert source["line_end"] == 2
    row = record().model_dump()
    row["claim"] = {"citation_id": claim["citation_id"]}
    row["sources"] = [{"citation_id": source["citation_id"]}]
    result = await tools.execute("evidence_record", {"record": json.dumps(row)})
    assert result["recorded_count"] == 1
    assert state["records"]["one"]["sources"][0]["quote"] == source["quote"]
    saved = await tools.execute("evidence_get", {"id": "one"})
    assert saved["calculation"] == record().calculation
    assert saved["sources"][0]["line_start"] == 2
    (tmp_path / "source.txt").write_text("Header\nChanged original text\n")
    result = await tools.execute("evidence_record", {"record": json.dumps(row)})
    assert result["error"] == "invalid_evidence"  # captured citations are rechecked after a source change
    with pytest.raises(ValueError, match="outside evidence contract"):
        await tools.execute("evidence_capture", {"path": "other.txt", "line_start": 1,
            "line_end": 1, "char_start": 0, "char_count": 20})


async def test_evidence_handoff_requires_progress_and_obeys_existing_limit(tmp_path):
    from agentlab.core.schemas import AgentResult
    svc = _svc(tmp_path)
    root = seed_demo_workspace(tmp_path / "ws")
    files(root)
    driver = svc.driver(root, "fake", "python")
    await driver.workspace.ensure_repo()
    run = await driver.create_async("audit")
    run.status = RunStatus.CODING
    svc.store.save_run(run)
    driver.recovery_options["evidence"] = {"contract": contract().model_dump(), "records": {}}
    async def save_progress(run, role, inp, out):
        driver.recovery_options["evidence"]["records"]["one"] = record().model_dump()
        return AgentResult(role=role, alias="test", model="test",
                           output=CoderOutput(edits=[], continue_evidence=True))
    driver._agent = save_progress
    await driver._coding(run)
    assert run.status == RunStatus.CODING
    assert driver.recovery_options["evidence_continuations"] == 1
    await driver._coding(run)  # same saved ID is not progress
    assert run.status == RunStatus.WAITING_HUMAN
    assert svc.store.pending_approval(run.id).payload["new_evidence_count"] == 0
    run.status = RunStatus.CODING
    svc.store.save_run(run)
    driver.recovery_options["evidence"]["records"] = {}
    driver.recovery_options["evidence_continuations"] = run.max_iter - 1
    await driver._coding(run)
    assert run.status == RunStatus.WAITING_HUMAN
    assert svc.store.pending_approval(run.id).payload["continuations_used"] == run.max_iter - 1


async def test_oversized_capture_returns_actionable_limits_without_saving(tmp_path):
    files(tmp_path)
    state = {"contract": contract().model_dump(), "records": {}, "searches": []}
    async def search(q):
        return {}
    tools = WorkerTools("coder", ["workspace_read"], GitWorkspace(tmp_path), None, search,
                        evidence_state=state)
    for end, count in [(1, 5000), (43, 2000)]:
        result = await tools.execute("evidence_capture", {"path": "answer.txt", "line_start": 1,
            "line_end": end, "char_start": 0, "char_count": count})
        assert result["error"] == "invalid_capture_range"
        assert result["limits"] == {"max_char_count": 2000, "max_lines": 31}
        assert not state.get("citations")
        assert not state["records"]
    result = await tools.execute("evidence_capture", {"path": "answer.txt", "line_start": 1,
        "line_end": 1, "char_start": 0, "char_count": 2000})
    assert result["citation_id"]
