"""SDK transport contracts without authentication, subprocesses or model calls."""
from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from agentlab.adapters.runtime.harness_clients import ClaudeClient, CodexClient


async def test_codex_native_harness_options_and_shutdown(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'empty-auth'))

    class Turn:
        id = 'turn'

        async def run(self):
            return SimpleNamespace(status=SimpleNamespace(value='completed'), final_response='done', usage=None)

    class Thread:
        id = 'thread'

        async def turn(self, prompt):
            calls.append(('prompt', prompt))
            return Turn()

    class SDK:
        def __init__(self, config):
            calls.append(('config', config))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            calls.append(('closed', True))

        async def thread_start(self, **kwargs):
            calls.append(('start', kwargs))
            return Thread()

    module = SimpleNamespace(AsyncCodex=SDK, CodexConfig=lambda **k: k,
                             ApprovalMode=SimpleNamespace(deny_all='deny_all'),
                             Sandbox=SimpleNamespace(workspace_write='workspace_write'))
    monkeypatch.setitem(sys.modules, 'openai_codex', module)
    updates = []
    reply = await CodexClient().run(source=tmp_path / 'source', state=tmp_path / 'state', prompt='implement',
                                     model='chosen-model', update=updates.append)
    assert reply.text == 'done' and not reply.metered
    start = next(v for k, v in calls if k == 'start')
    assert start['cwd'] == str(tmp_path / 'source')
    assert start['sandbox'] == 'workspace_write' and start['approval_mode'] == 'deny_all'
    assert start['config']['sandbox_workspace_write']['exclude_slash_tmp']
    assert not start['config']['sandbox_workspace_write']['network_access']
    assert not start['config']['agents']['enabled']
    assert not start['config']['allow_login_shell']
    assert updates[:2] == [{'session_id': 'thread'}, {'turn_id': 'turn'}]
    assert calls[-1] == ('closed', True)

    async def cancel(_self):
        raise asyncio.CancelledError()

    async def interrupt(_self):
        calls.append(('interrupted', True))

    monkeypatch.setattr(Turn, 'run', cancel)
    monkeypatch.setattr(Turn, 'interrupt', interrupt, raising=False)
    with pytest.raises(asyncio.CancelledError):
        await CodexClient().run(source=tmp_path / 'source', state=tmp_path / 'state', prompt='implement',
                                model=None, update=updates.append)
    assert calls[-2:] == [('interrupted', True), ('closed', True)]


@pytest.mark.parametrize('success,structured', [(True, {'verdict': 'APPROVE'}), (False, {}), (True, None)])
async def test_claude_native_options_and_terminal_result(tmp_path, monkeypatch, success, structured):
    options = []

    class System:
        subtype = 'init'
        data = {'session_id': 'review-session'}

    class Result:
        session_id = 'review-session'
        subtype = 'success' if success else 'error_during_execution'
        is_error = not success
        structured_output = structured
        usage = {'input_tokens': 10, 'output_tokens': 5}
        total_cost_usd = 0.01

    class SDK:
        def __init__(self, **kwargs):
            options.append(kwargs['options'])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def query(self, prompt):
            assert prompt == 'review'

        async def receive_response(self):
            yield System()
            yield Result()

    monkeypatch.setitem(sys.modules, 'claude_agent_sdk', SimpleNamespace(
        ClaudeAgentOptions=lambda **k: k, ClaudeSDKClient=SDK, HookMatcher=lambda **k: k,
        SystemMessage=System, ResultMessage=Result))
    invocation = ClaudeClient().run(source=tmp_path / 'source', state=tmp_path / 'state', prompt='review',
                                    model='chosen-reviewer', schema={'type': 'object'}, update=lambda _: None)
    if success and structured is not None:
        result = await invocation
        assert result.structured == structured and result.usage.cost_cents == 1
    else:
        with pytest.raises(RuntimeError, match='claude_review_not_completed'):
            await invocation
    opts = options[0]
    assert opts['tools'] == ['Read', 'Glob', 'Grep']
    assert opts['setting_sources'] == [] and opts['strict_mcp_config']
    assert opts['permission_mode'] == 'dontAsk'
    assert 'Bash' in opts['disallowed_tools'] and 'Agent' in opts['disallowed_tools']
    assert 'StructuredOutput' in opts['allowed_tools']
    assert opts['output_format'] == {'type': 'json_schema', 'schema': {'type': 'object'}}
    assert opts['model'] == 'chosen-reviewer'
