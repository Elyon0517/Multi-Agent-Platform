from __future__ import annotations

import json
import stat

import pytest

from agentlab.adapters.harness_workspace import HarnessWorkspace
from agentlab.adapters.runtime.harness import HarnessRuntime
from agentlab.adapters.runtime.harness_clients import HarnessReply, review_tool_policy
from agentlab.core.ports import RunContext
from agentlab.core.schemas import AgentInput, CoderOutput, RunStatus, Usage
from tests.unit.test_driver import make_driver
from tests.unit.test_edit_journal import ProcessDied, restore


class Client:
    def __init__(self, action=None, structured=None):
        self.calls = []
        self.action = action
        self.structured = structured

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        kwargs['update']({'session_id': f'session-{len(self.calls)}', 'turn_id': 'turn'})
        if self.action:
            self.action(kwargs)
        return HarnessReply(text='implemented', structured=self.structured,
                            usage=Usage(tokens_in=10, tokens_out=5, cost_cents=1), metered=True, model='sdk-model')


@pytest.fixture(autouse=True)
def sdk_version(monkeypatch):
    monkeypatch.setattr('agentlab.adapters.runtime.harness.version', lambda _: 'test-sdk-1')


async def setup(cfg, tmp_path, coder=None, reviewer=None):
    driver = await make_driver(cfg, tmp_path)
    driver.cfg = cfg.model_copy(update={'harness': cfg.harness.model_copy(update={'enabled': True})})
    raw = driver.runtime
    coder = coder or Client(lambda k: (k['source'] / 'calc.py').write_text('def add(a, b):\n    return a + b\n'))
    reviewer = reviewer or Client(structured={'reviewer_id': 'untrusted', 'verdict': 'APPROVE'})
    runtime = HarnessRuntime(driver.cfg, lambda: raw, driver.store, driver.blobs, driver.workspace,
                             tmp_path / 'harness', coder, reviewer)
    driver.runtime = runtime
    return driver, coder, reviewer


async def test_coding_gate_review_and_signoff_share_revision(cfg, tmp_path):
    d, coder, reviewer = await setup(cfg, tmp_path)
    run = await d.run(d.create('fix add').id)
    assert run.paused_reason == 'signoff'
    assert len(coder.calls) == len(reviewer.calls) == 1
    assert coder.calls[0]['source'] != d.workspace.root
    assert reviewer.calls[0]['source'] != coder.calls[0]['source']
    assert '"files"' not in coder.calls[0]['prompt']
    assert 'workspace_write' not in coder.calls[0]['prompt']
    assert not reviewer.calls[0]['source'].stat().st_mode & stat.S_IWUSR
    invocations = d.store.records('harness_invocation')
    review = next(r for r in invocations if r['role'] == 'correctness-reviewer')
    assert review['base_revision'] == d.recovery_options['revision_id']
    verdict = json.loads(d.blobs.get(review['result_ref']))
    assert verdict['revision_id'] == review['base_revision']
    assert verdict['reviewer_id'] == 'correctness-reviewer'
    operations = d.store.records('edit_operation')
    assert len(operations) == 1 and operations[0]['source'] == 'coder_output'
    assert all(r['status'] == 'completed' for r in invocations)
    assert len([a for a in d.store.records('attempt') if a.get('backend')]) == 2
    assert d.decide(run.id, 'approve').status == RunStatus.DONE


async def test_review_changes_request_returns_to_codex_with_new_revision(cfg, tmp_path):
    def action(k):
        content = 'def add(a, b):\n    return a + b\n'
        if len(coder.calls) > 1:
            content += '# clarified\n'
        (k['source'] / 'calc.py').write_text(content)

    from tests.conftest import finding
    f = finding(conf=1, file='calc.py').model_dump(mode='json')
    reviewer = Client(structured={'reviewer_id': 'r', 'verdict': 'REQUEST_CHANGES', 'findings': [f]})
    d, coder, reviewer = await setup(cfg, tmp_path, coder=Client(action), reviewer=reviewer)
    original = reviewer.run

    async def review(**kwargs):
        if reviewer.calls:
            reviewer.structured = {'reviewer_id': 'r', 'verdict': 'APPROVE'}
        return await original(**kwargs)

    reviewer.run = review
    run = await d.run(d.create('fix add').id)
    assert run.paused_reason == 'signoff'
    assert len(coder.calls) == len(reviewer.calls) == 2
    assert 'bug' in coder.calls[1]['prompt']
    revisions = {r['base_revision'] for r in d.store.records('harness_invocation')
                 if r['role'] == 'correctness-reviewer'}
    assert len(revisions) == 2


async def test_authoritative_human_edit_during_sdk_is_never_overwritten(cfg, tmp_path):
    d, coder, _ = await setup(cfg, tmp_path)

    def action(k):
        (k['source'] / 'calc.py').write_text('sdk output\n')
        (d.workspace.root / 'calc.py').write_text('human edit\n')

    coder.action = action
    run = await d.run(d.create('fix add').id)
    assert run.paused_reason == 'edit_conflict'
    assert (d.workspace.root / 'calc.py').read_text() == 'human edit\n'
    assert not d.store.records('edit_operation')


@pytest.mark.parametrize('change', ['delete', 'binary', 'mode', 'secret', 'symlink', 'nested'])
async def test_unsupported_output_is_rejected_before_any_promotion(cfg, tmp_path, change):
    d, coder, _ = await setup(cfg, tmp_path)
    original = (d.workspace.root / 'calc.py').read_text()

    def action(k):
        source = k['source']
        (source / 'calc.py').write_text('changed\n')
        if change == 'delete':
            (source / 'test_calc.py').unlink()
        elif change == 'binary':
            (source / 'binary').write_bytes(b'\0\xff')
        elif change == 'mode':
            (source / 'calc.py').chmod(0o755)
        elif change == 'secret':
            (source / '.env').write_text('secret')
        elif change == 'nested':
            (source / 'nested' / '.git').mkdir(parents=True)
            (source / 'nested' / 'a.py').write_text('code')
        else:
            (source / 'link').symlink_to(d.workspace.root / 'calc.py')

    coder.action = action
    run = await d.run(d.create('fix add').id)
    assert run.status == RunStatus.WAITING_HUMAN and run.paused_reason != 'signoff'
    assert (d.workspace.root / 'calc.py').read_text() == original
    assert not d.store.records('edit_operation')


@pytest.mark.parametrize('output', [None, {}, {'reviewer_id': 'r', 'verdict': 'invalid'}])
async def test_invalid_review_never_signs_off(cfg, tmp_path, output):
    d, _, _ = await setup(cfg, tmp_path, reviewer=Client(structured=output))
    run = await d.run(d.create('fix add').id)
    assert run.paused_reason != 'signoff' and run.status == RunStatus.WAITING_HUMAN
    assert not d.store.iterations(run.id)[-1].verdicts


async def test_review_mutation_detected_even_if_tool_policy_is_bypassed(cfg, tmp_path):
    def mutate(k):
        target = k['source'] / 'calc.py'
        target.chmod(0o644)
        target.write_text('tampered')

    d, _, _ = await setup(cfg, tmp_path, reviewer=Client(action=mutate, structured={'reviewer_id': 'r', 'verdict': 'APPROVE'}))
    run = await d.run(d.create('fix add').id)
    assert run.paused_reason == 'edit_conflict'
    assert 'tampered' not in (d.workspace.root / 'calc.py').read_text()


async def test_completed_response_and_partial_promotion_recover_without_sdk_replay(cfg, tmp_path, monkeypatch):
    d, coder, _ = await setup(cfg, tmp_path)
    d.gate = None

    def action(k):
        (k['source'] / 'a.py').write_text('a = 2\n')
        (k['source'] / 'b.py').write_text('b = 2\n')

    coder.action = action
    run = d.create('update two files')
    apply = d.workspace.apply_edits

    def die(edits, expected_hashes=None):
        if edits[0].path == 'b.py':
            raise ProcessDied()
        return apply(edits, expected_hashes)

    with monkeypatch.context() as patch:
        patch.setattr(d.workspace, 'apply_edits', die)
        with pytest.raises(ProcessDied):
            await d.run(run.id)
    assert (d.workspace.root / 'a.py').exists() and not (d.workspace.root / 'b.py').exists()
    recovered = restore(d, run, d.runtime)
    # Bind runtime to restored workspace, as the production factory does.
    d.runtime.workspace = recovered.workspace
    run = await recovered.run(run.id)
    assert len(coder.calls) == 1
    assert (d.workspace.root / 'b.py').read_text() == 'b = 2\n'
    assert run.paused_reason == 'signoff'
    ledger = [u for u in d.store.usage_entries() if u['role'] == 'coder']
    assert len(ledger) == 1


async def test_crash_after_sdk_completion_before_normalization_recovers_paid_reply(cfg, tmp_path, monkeypatch):
    d, coder, _ = await setup(cfg, tmp_path)
    original = HarnessWorkspace.edits

    with monkeypatch.context() as patch:
        patch.setattr(HarnessWorkspace, 'edits', lambda *_: (_ for _ in ()).throw(ProcessDied()))
        with pytest.raises(ProcessDied):
            await d.run(d.create('fix add').id)
    run = d.store.list_runs()[0]
    assert next(r for r in d.store.records('harness_invocation') if r['role'] == 'coder')['status'] == 'sdk_completed'
    # Existing interrupted-call approval remains the control point.
    run = await d.run(run.id)
    assert run.paused_reason == 'interrupted_call'
    d.decide(run.id, 'approve')
    run = await d.run(run.id)
    assert run.paused_reason == 'signoff' and len(coder.calls) == 1
    assert HarnessWorkspace.edits is original
    assert len([u for u in d.store.usage_entries() if u['role'] == 'coder']) == 1


async def test_unknown_sdk_execution_is_not_replayed(cfg, tmp_path):
    d, coder, _ = await setup(cfg, tmp_path)
    coder.action = lambda _: (_ for _ in ()).throw(ProcessDied())
    with pytest.raises(ProcessDied):
        await d.run(d.create('fix add').id)
    run = d.store.list_runs()[0]
    run = await d.run(run.id)
    assert run.paused_reason == 'interrupted_call'
    d.decide(run.id, 'approve')
    run = await d.run(run.id)
    assert run.status == RunStatus.WAITING_HUMAN
    assert len(coder.calls) == 1
    # Explicit rejection creates a new scope/copy rather than reopening an unknown writer.
    d.decide(run.id, 'reject', feedback='start a new isolated attempt')
    coder.action = lambda k: (k['source'] / 'calc.py').write_text('def add(a, b):\n    return a + b\n')
    run = await d.run(run.id)
    assert len(coder.calls) == 2 and run.paused_reason == 'signoff'
    assert coder.calls[0]['source'] != coder.calls[1]['source']


async def test_stale_signoff_runs_fresh_review(cfg, tmp_path):
    d, _, reviewer = await setup(cfg, tmp_path)
    run = await d.run(d.create('fix add').id)
    old_revision = d.recovery_options['revision_id']
    with (d.workspace.root / 'calc.py').open('a') as stream:
        stream.write('# human change after review\n')
    run = d.decide(run.id, 'approve')
    assert run.paused_reason == 'workspace_changed'
    d.decide(run.id, 'approve')
    run = await d.run(run.id)
    assert run.paused_reason == 'signoff' and len(reviewer.calls) == 2
    assert d.recovery_options['revision_id'] != old_revision


@pytest.mark.parametrize('name,args,deny', [
    ('Edit', {'file_path': 'a.py'}, True), ('Bash', {'command': 'pwd'}, True),
    ('Agent', {}, True), ('mcp__write', {}, True), ('Read', {'file_path': '/etc/passwd'}, True),
    ('Read', {'file_path': 'a.py'}, False), ('Grep', {'path': '../'}, True),
    ('Glob', {'pattern': '../*'}, True), ('Glob', {'pattern': '/etc/*'}, True),
    ('Glob', {'pattern': '{../*,*}'}, True), ('Read', {'file_path': '~/secret'}, True),
    ('StructuredOutput', {}, False),
])
async def test_review_hook_is_a_read_boundary(tmp_path, name, args, deny):
    result = await review_tool_policy({'tool_name': name, 'tool_input': args}, None, None, source=tmp_path)
    assert bool(result) == deny


async def test_completed_invocation_replays_cached_output_not_sdk(cfg, tmp_path):
    d, coder, _ = await setup(cfg, tmp_path)
    run = d.create('fix add')
    revision = d.workspace.review_snapshot()[0]
    inp = AgentInput(run_id=run.id, iteration=1, goal='fix add', context={
        '_harness_scope': 'scope', '_harness_revision': revision, '_harness_baseline': d.workspace.edit_baseline()})
    first = await d.runtime.run_agent('coder', inp, CoderOutput, RunContext(run, lambda _: None))
    second = await d.runtime.run_agent('coder', inp, CoderOutput, RunContext(run, lambda _: None))
    assert first.output == second.output and len(coder.calls) == 1
    assert 'return a - b' in (d.workspace.root / 'calc.py').read_text()  # No direct write to authoritative workspace.


async def test_sdk_create_and_restore_use_same_factory_without_raw_gateway(cfg, tmp_path):
    from agentlab.bootstrap import build_services
    from agentlab.settings import Settings

    template = await make_driver(cfg, tmp_path)
    services = build_services(Settings(config_dir=cfg.root, data_dir=tmp_path / 'data',
                                       env_file=tmp_path / 'absent.env', store_backend='memory',
                                       runtime='sdk', sandbox='local'))
    d = services.driver(template.workspace.root)
    run = d.create('fix add')
    recovered = services.restore_driver(run.id)
    assert isinstance(d.runtime, HarnessRuntime) and isinstance(recovered.runtime, HarnessRuntime)
    assert recovered.runtime.workspace is recovered.workspace
    assert recovered.cfg.harness.enabled and recovered.cfg.reviewer_roles == ['correctness-reviewer']
    assert recovered.runtime_factory().workspace is recovered.workspace


async def test_dirty_untracked_and_binary_source_are_copied_without_user_index_changes(cfg, tmp_path):
    d, _, _ = await setup(cfg, tmp_path)
    root = d.workspace.root
    (root / 'calc.py').write_text('dirty content\n')
    (root / 'new.txt').write_text('untracked\n')
    (root / 'image.bin').write_bytes(b'\x00\xff')
    d.create('inspect')
    index = d.workspace._git_bytes('ls-files', '--stage')
    snapshot = HarnessWorkspace(d.workspace, tmp_path / 'copy')
    manifest = snapshot.create(d.workspace.review_snapshot()[0], d.workspace.edit_baseline())
    assert (snapshot.root / 'calc.py').read_text() == 'dirty content\n'
    assert (snapshot.root / 'new.txt').read_text() == 'untracked\n'
    assert (snapshot.root / 'image.bin').read_bytes() == b'\x00\xff'
    assert snapshot.edits(manifest)[0] == []
    assert d.workspace._git_bytes('ls-files', '--stage') == index


async def test_tampered_copy_after_sdk_completion_is_not_promoted(cfg, tmp_path, monkeypatch):
    d, coder, _ = await setup(cfg, tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(HarnessWorkspace, 'edits', lambda *_: (_ for _ in ()).throw(ProcessDied()))
        with pytest.raises(ProcessDied):
            await d.run(d.create('fix add').id)
    (coder.calls[0]['source'] / 'calc.py').write_text('external change to scratch\n')
    run = d.store.list_runs()[0]
    await d.run(run.id)
    d.decide(run.id, 'approve')
    run = await d.run(run.id)
    assert run.paused_reason == 'edit_conflict' and len(coder.calls) == 1
    assert not d.store.records('edit_operation')


async def test_existing_manual_project_bindings_remain_usable_with_single_reviewer(cfg, tmp_path):
    from agentlab.core.project_config import Binding, ProjectSettings, validate_settings, worker_roles

    sdk_cfg = cfg.model_copy(update={'harness': cfg.harness.model_copy(update={'enabled': True})})
    settings = ProjectSettings(mode='manual', bindings={r: Binding(alias=cfg.model_policy.roles[r].primary, task=r)
                                                      for r in worker_roles(cfg)})
    validate_settings(settings, sdk_cfg)
    assert 'arch-reviewer' not in worker_roles(sdk_cfg)
    assert 'correctness-reviewer' in worker_roles(sdk_cfg)


async def test_sdk_version_change_does_not_start_another_paid_invocation(cfg, tmp_path, monkeypatch):
    d, coder, _ = await setup(cfg, tmp_path)
    run = d.create('fix add')
    revision = d.workspace.review_snapshot()[0]
    inp = AgentInput(run_id=run.id, iteration=1, goal='fix add', context={
        '_harness_scope': 'scope', '_harness_revision': revision, '_harness_baseline': d.workspace.edit_baseline()})
    ctx = RunContext(run, lambda _: None)
    await d.runtime.run_agent('coder', inp, CoderOutput, ctx)
    monkeypatch.setattr('agentlab.adapters.runtime.harness.version', lambda _: 'different-sdk')
    with pytest.raises(Exception, match='harness_sdk_version_changed'):
        await d.runtime.run_agent('coder', inp, CoderOutput, ctx)
    assert len(coder.calls) == 1


async def test_native_completion_summary_cannot_bypass_review_as_readonly_report(cfg, tmp_path):
    d, coder, reviewer = await setup(cfg, tmp_path, coder=Client())
    run = await d.run(d.create('fix add').id)
    assert run.status == RunStatus.WAITING_HUMAN and run.paused_reason == 'no_changes'
    assert len(coder.calls) == 1 and not reviewer.calls
    assert not d.store.artifacts(run.id, 'report')


async def test_failed_sdk_review_keeps_returned_usage_without_approving(cfg, tmp_path):
    from agentlab.adapters.runtime.harness_clients import HarnessFailure

    class FailedReview(Client):
        async def run(self, **kwargs):
            raise HarnessFailure('claude_review_not_completed', HarnessReply(
                usage=Usage(tokens_in=20, tokens_out=3, cost_cents=2), metered=True, model='claude-test'))

    d, _, _ = await setup(cfg, tmp_path, reviewer=FailedReview())
    run = await d.run(d.create('fix add').id)
    assert run.status == RunStatus.WAITING_HUMAN and run.paused_reason != 'signoff'
    rows = [u for u in d.store.usage_entries() if u['role'] == 'correctness-reviewer']
    assert len(rows) == 1 and rows[0]['cost_cents'] == 2
    assert next(r for r in d.store.records('harness_invocation') if r['backend'] == 'claude')['status'] == 'failed'


async def test_jsonb_key_reordering_reuses_same_completed_invocation(cfg, tmp_path):
    import copy

    d, coder, _ = await setup(cfg, tmp_path)
    run = d.create('fix add')
    revision = d.workspace.review_snapshot()[0]
    inp = AgentInput(run_id=run.id, iteration=1, goal='fix add', context={
        '_harness_scope': 'scope', '_harness_revision': revision, '_harness_baseline': d.workspace.edit_baseline(),
        'memory': {'z': 'last', 'a': 'first'}, 'assignment': {'task': 'fix', 'alias': 'strong'}})
    ctx = RunContext(run, lambda _: None)
    first = await d.runtime.run_agent('coder', inp, CoderOutput, ctx)
    # JSONB's canonical object order differs from Python insertion order, including nested dictionaries.
    recovered = AgentInput.model_validate(json.loads(json.dumps(inp.model_dump(mode='json'), sort_keys=True)))
    assert list(inp.context) != list(recovered.context)
    second = await d.runtime.run_agent('coder', copy.deepcopy(recovered), CoderOutput, ctx)
    assert first.output == second.output and len(coder.calls) == 1
    assert len(d.store.records('harness_invocation')) == 1


async def test_unknown_scope_cannot_be_reopened_by_prompt_fingerprint_change(cfg, tmp_path):
    d, coder, _ = await setup(cfg, tmp_path)
    run = d.create('fix add')
    inp = AgentInput(run_id=run.id, iteration=1, goal='fix add', context={
        '_harness_scope': 'scope', '_harness_revision': d.workspace.review_snapshot()[0],
        '_harness_baseline': d.workspace.edit_baseline(), 'memory': {'a': 'first'}})
    coder.action = lambda _: (_ for _ in ()).throw(ProcessDied())
    ctx = RunContext(run, lambda _: None)
    with pytest.raises(ProcessDied):
        await d.runtime.run_agent('coder', inp, CoderOutput, ctx)
    # Old-format checkpoints or changed harness prompts must also fail closed for an existing scope.
    inp.context['memory'] = {'changed': 'fingerprint'}
    with pytest.raises(Exception, match='harness_interrupted_requires_replan'):
        await d.runtime.run_agent('coder', inp, CoderOutput, ctx)
    assert len(coder.calls) == 1
    assert len(d.store.records('harness_invocation')) == 1
