from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agentlab.api.app import create_app
from agentlab.core.conversation import Conversation
from agentlab.core.schemas import Finding, Plan, RunStatus, Severity
from agentlab.core.session.store import get_thread
from agentlab.demo import seed_demo_workspace
from tests.unit.test_memory_project import _svc


@pytest.mark.parametrize('language, checks', [('python', 'passed'), ('go', 'not_run')])
async def test_fake_signoff_report_matches_plan_checks_final_reviews_and_conversation(tmp_path, language, checks):
    svc = _svc(tmp_path)
    thread = Conversation(project_id='default', title='Final review')
    svc.store.put_record('thread', thread.id, thread.model_dump(mode='json'))
    driver = svc.driver(seed_demo_workspace(tmp_path / language), 'fake', language)
    original = driver.runtime._scripts['arch-reviewer']

    def review(inp):
        verdict = original(inp)
        if not verdict.findings:
            return verdict.model_copy(update={'findings': [Finding(
                severity=Severity.MINOR, category='arch', file='calc.py', line=1,
                issue='Consider documenting numeric input types', confidence=0.9,
            )]})
        return verdict

    driver.runtime._scripts['arch-reviewer'] = review
    await driver.workspace.ensure_repo()
    run = await driver.run((await driver.create_async('Repair calc.add without changing its public API', thread_id=thread.id)).id)
    assert run.status == RunStatus.WAITING_HUMAN and run.paused_reason == 'signoff'
    approval = svc.store.pending_approval(run.id)
    report = approval.report
    plan = Plan.model_validate_json(svc.blobs.get(svc.store.artifacts(run.id, 'plan')[-1].content_ref))
    assert report.goal == run.goal and report.acceptance_criteria == plan.acceptance_criteria
    assert report.automated_checks == checks == approval.payload['automated_checks']
    final_findings = [f for v in svc.store.iterations(run.id)[-1].verdicts for f in v.findings]
    assert report.findings == final_findings and len(report.findings) == 1
    assert report.findings[0].severity == Severity.MINOR
    assert all('lacks a docstring' not in f.issue for f in report.findings)
    assert any(f.severity == Severity.MAJOR for it in svc.store.iterations(run.id)[:-1]
               for verdict in it.verdicts for f in verdict.findings)
    if checks == 'passed':
        full = json.loads(svc.blobs.get(svc.store.artifacts(run.id, 'gate')[-1].content_ref))
        assert full['mode'] == 'full' and full['passed']
    else:
        assert not svc.store.artifacts(run.id, 'gate')
    with TestClient(create_app(svc)) as client:
        saved = client.get(f'/runs/{run.id}').json()['pending_approval']['report']
        assert saved == report.model_dump(mode='json')
    restored = svc.restore_driver(run.id)
    assert restored.store.pending_approval(run.id).report == report
    summaries = [m for m in get_thread(svc.store, thread.id, 'default').messages if m.kind == 'summary']
    assert len(summaries) == 1 and summaries[0].payload['report'] == saved
    text = summaries[0].text
    assert run.goal in text and all(criterion in text for criterion in report.acceptance_criteria)
    assert 'Consider documenting numeric input types' in text and 'lacks a docstring' not in text
    assert ('未经过自动测试' in text) == (checks == 'not_run')
    assert ('FULL Gate 通过' in text) == (checks == 'passed')
    # Report and summary use saved evidence, with no additional summary model turn.
    assert svc.store.records('root_turn') == []
    event = next(e for e in svc.store.events(run.id) if e.type == 'approval.requested')
    assert event.payload['report'] == saved
