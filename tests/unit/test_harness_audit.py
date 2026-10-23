from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from agentlab.adapters.harness_workspace import HarnessWorkspace, digest
from agentlab.core.ports import EditConflict, RunContext
from agentlab.core.schemas import AgentInput, CoderOutput, Verdict
from tests.unit.test_edit_journal import ProcessDied
from tests.unit.test_harness_runtime import Client, setup


@pytest.fixture(autouse=True)
def sdk_version(monkeypatch):
    monkeypatch.setattr('agentlab.adapters.runtime.harness.version', lambda _: 'audit-sdk')


@pytest.mark.parametrize("role", ["coder", "correctness-reviewer"])
async def test_prepared_copy_is_rechecked_before_resuming_sdk(cfg, tmp_path, role):
    d, coder, reviewer = await setup(cfg, tmp_path)
    client = coder if role == "coder" else reviewer
    output_type = CoderOutput if role == "coder" else Verdict
    run = d.create('fix add')
    original = (d.workspace.root / 'calc.py').read_bytes()
    inp = AgentInput(run_id=run.id, iteration=1, goal='fix add',
                     revision_id=d.workspace.review_snapshot()[0] if role != "coder" else None, context={
        '_harness_scope': 'scope', '_harness_revision': d.workspace.review_snapshot()[0],
        '_harness_baseline': d.workspace.edit_baseline()})

    def die(_):
        raise ProcessDied()

    with pytest.raises(ProcessDied):
        await d.runtime.run_agent(role, inp, output_type, RunContext(run, lambda _: None, attempt_started=die))
    record = d.store.records('harness_invocation')[0]
    assert record['status'] == 'prepared' and not client.calls
    target = Path(record['directory']) / 'source/calc.py'
    target.chmod(0o644)
    target.write_text('human change to interrupted private copy\n')
    with pytest.raises(EditConflict):
        await d.runtime.run_agent(role, inp, output_type, RunContext(run, lambda _: None))
    assert not client.calls and (d.workspace.root / 'calc.py').read_bytes() == original


async def test_review_copy_uses_captured_bytes_not_transient_live_reads(cfg, tmp_path, monkeypatch):
    d, _, _ = await setup(cfg, tmp_path)
    d.create('inspect')
    revision = d.workspace.review_snapshot()[0]
    original = (d.workspace.root / 'calc.py').read_bytes()
    snapshot = d.workspace._snapshot
    read = Path.read_bytes
    capturing = False

    def captured():
        nonlocal capturing
        capturing = True
        try:
            return snapshot()
        finally:
            capturing = False

    def transient(path):
        # A writer's transient version is visible between the authoritative revision captures,
        # then restored before the final capture (A -> B -> A).
        if path == d.workspace.root / 'calc.py' and not capturing:
            return b'uncaptured transient version\n'
        return read(path)

    monkeypatch.setattr(d.workspace, '_snapshot', captured)
    monkeypatch.setattr(Path, 'read_bytes', transient)
    copy = HarnessWorkspace(d.workspace, tmp_path / 'review-copy')
    copy.create(revision)
    assert (copy.root / 'calc.py').read_bytes() == original
    assert d.workspace.review_snapshot()[0] == revision


async def test_export_preserves_exact_crlf_bytes(cfg, tmp_path):
    d, _, _ = await setup(cfg, tmp_path)
    d.create('inspect')
    copy = HarnessWorkspace(d.workspace, tmp_path / 'copy')
    baseline = copy.create(d.workspace.review_snapshot()[0])
    content = b'def add(a, b):\r\n    return a + b\r\n'
    (copy.root / 'calc.py').write_bytes(content)
    edits, manifest = copy.edits(baseline)
    assert edits[0].content.encode() == content
    assert digest(edits[0].content.encode()) == manifest['calc.py']['hash']


async def test_export_checks_read_bytes_against_frozen_manifest(cfg, tmp_path, monkeypatch):
    d, _, _ = await setup(cfg, tmp_path)
    d.create('inspect')
    copy = HarnessWorkspace(d.workspace, tmp_path / 'copy')
    baseline = copy.create(d.workspace.review_snapshot()[0])
    path = copy.root / 'calc.py'
    path.write_text('stable SDK output\n')
    open_file = Path.open
    reads = 0

    def transient_open(target, *args, **kwargs):
        nonlocal reads
        if target == path:
            reads += 1
            if reads == 2:
                # A transient version is read by export, while both manifest scans see A.
                mode = kwargs.get('mode', args[0] if args else 'r')
                data = b'transient non-SDK content\n'
                return io.BytesIO(data) if 'b' in mode else io.StringIO(data.decode())
        return open_file(target, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', transient_open)
    with pytest.raises(EditConflict):
        copy.edits(baseline)


async def test_legacy_unknown_reviewer_without_iteration_cannot_be_reissued(cfg, tmp_path):
    d, _, reviewer = await setup(cfg, tmp_path)
    run = d.create('inspect')
    inp = AgentInput(run_id=run.id, iteration=1, goal='inspect', revision_id=d.workspace.review_snapshot()[0])
    reviewer.action = lambda _: (_ for _ in ()).throw(ProcessDied())
    ctx = RunContext(run, lambda _: None)
    with pytest.raises(ProcessDied):
        await d.runtime.run_agent('correctness-reviewer', inp, Verdict, ctx)
    record = d.store.records('harness_invocation')[0]
    record.pop('iteration')  # Checkpoints written before iteration was added to native records.
    d.store.put_record('harness_invocation', record['id'], json.loads(json.dumps(record, sort_keys=True)))
    inp.context['changed'] = 'fingerprint'
    with pytest.raises(Exception, match='harness_interrupted_requires_replan'):
        await d.runtime.run_agent('correctness-reviewer', inp, Verdict, ctx)
    assert len(reviewer.calls) == 1


async def test_crlf_export_journal_and_review_snapshot_share_exact_bytes(cfg, tmp_path):
    content = b"def add(a, b):\r\n    return a + b\r\n"
    coder = Client(lambda k: (k['source'] / 'calc.py').write_bytes(content))
    d, _, reviewer = await setup(cfg, tmp_path, coder=coder)
    run = await d.run(d.create('fix add').id)
    assert run.paused_reason == 'signoff'
    assert (d.workspace.root / 'calc.py').read_bytes() == content
    assert (reviewer.calls[0]['source'] / 'calc.py').read_bytes() == content
    op = d.store.records('edit_operation')[0]
    assert op['files'][0]['after_hash'] == digest(content)
    snapshot = next(r for r in d.store.records('harness_invocation') if r['backend'] == 'claude')
    assert snapshot['base_revision'] == d.recovery_options['revision_id']
