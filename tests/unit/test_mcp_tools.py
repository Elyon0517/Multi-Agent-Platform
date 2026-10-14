import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agentlab.adapters.mcp import McpConfig, McpHub, McpTool, load_mcp_config
from agentlab.api.app import create_app
from agentlab.core.conversation import RootTurn
from agentlab.core.llm.structured import Completion
from tests.unit.test_project_experience import services
from tests.unit.test_root_session import call, root_runtime

READ = McpTool("github", "get_file_contents", "Read a file", {"type": "object", "properties": {}}, True)
WRITE = McpTool("github", "create_pull_request", "Open a PR", {"type": "object", "properties": {}}, False)


class FakeHub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def tools(self, role: str) -> list[McpTool]:
        return [READ, WRITE] if role == "root" else [READ, WRITE] if role == "planner" else []

    async def call(self, tool: McpTool, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool.name, args))
        return {"text": f"{tool.name} ok"}

    def status(self) -> list[dict[str, Any]]:
        return []

    async def close(self) -> None:
        return None


def _chat(svc, completions):
    root = root_runtime(svc.cfg, completions)
    original = svc.runtime
    svc.runtime = lambda name=None, cfg=None: root if name is None else original(name, cfg)


def test_read_only_tools_run_and_writes_wait_for_the_user(tmp_path: Path) -> None:
    svc = services(tmp_path)
    hub = svc.mcp = FakeHub()  # type: ignore[assignment]
    _chat(svc, [
        call(READ.qualified, {"path": "README.md"}),
        call(WRITE.qualified, {"title": "Fix"}),
        Completion(RootTurn(intent="answer", reply="Asked to open a PR").model_dump_json(), 10, 5),
    ])
    with TestClient(create_app(svc)) as client:
        thread = client.post("/threads", json={"title": "mcp"}).json()
        assert client.post(f"/threads/{thread['id']}/messages", json={"text": "open a PR"}).status_code == 200
        assert hub.calls == [("get_file_contents", {"path": "README.md"})]  # the write did not run

        messages = client.get("/threads").json()[0]["messages"]
        card = next(m for m in messages if m["kind"] == "tool_approval")
        approval = card["payload"]["approval_id"]
        url = f"/threads/{thread['id']}/tool-approvals/{approval}"
        assert client.post(url, json={"decision": "allow"}).json() == {"status": "done"}
        assert hub.calls[-1] == ("create_pull_request", {"title": "Fix"})
        assert client.post(url, json={"decision": "deny"}).status_code == 409  # decided once
        assert client.post(f"/threads/other/tool-approvals/{approval}", json={"decision": "allow"}).status_code == 404
        result = [m for m in client.get("/threads").json()[0]["messages"] if m["kind"] == "tool_result"]
        assert len(result) == 1 and "create_pull_request ok" in result[0]["text"]


def test_denied_writes_never_run(tmp_path: Path) -> None:
    svc = services(tmp_path)
    hub = svc.mcp = FakeHub()  # type: ignore[assignment]
    _chat(svc, [call(WRITE.qualified, {"title": "x"}),
                Completion(RootTurn(intent="answer", reply="waiting").model_dump_json(), 10, 5)])
    with TestClient(create_app(svc)) as client:
        thread = client.post("/threads", json={"title": "mcp"}).json()
        client.post(f"/threads/{thread['id']}/messages", json={"text": "comment"})
        card = next(m for m in client.get("/threads").json()[0]["messages"] if m["kind"] == "tool_approval")
        url = f"/threads/{thread['id']}/tool-approvals/{card['payload']['approval_id']}"
        assert client.post(url, json={"decision": "deny"}).json() == {"status": "denied"}
        assert hub.calls == []


def test_planner_only_receives_read_only_tools(tmp_path: Path) -> None:
    svc = services(tmp_path)
    svc.mcp = FakeHub()  # type: ignore[assignment]
    specs, execute = asyncio.run(svc.hooks.external_tools("planner"))
    assert [s["function"]["name"] for s in specs] == [READ.qualified]
    assert asyncio.run(execute(READ.qualified, {})) == {"text": "get_file_contents ok"}


def test_config_is_strict_and_names_fit_model_apis(tmp_path: Path) -> None:
    (tmp_path / "mcp.yaml").write_text("servers:\n  x:\n    command: echo\n    roles: [root]\n    surprise: 1\n")
    with pytest.raises(ValueError):
        load_mcp_config(tmp_path)
    assert load_mcp_config(tmp_path / "missing") == McpConfig()
    long = McpTool("server.with dots", "t" * 80, "", {}, True)
    assert len(long.qualified) <= 64 and "." not in long.qualified and " " not in long.qualified


def test_env_placeholders_resolve_from_env_file(tmp_path: Path) -> None:
    hub = McpHub(McpConfig(), lambda: {"TOKEN_FOR_TEST": "abc"})
    assert hub._resolve_env({"A": "${TOKEN_FOR_TEST}", "B": "plain"}) == {"A": "abc", "B": "plain"}


@pytest.mark.parametrize('project_chat', [False, True])
async def test_tool_execution_blocks_conversation_and_project_deletion(tmp_path: Path, project_chat: bool) -> None:
    from httpx import ASGITransport, AsyncClient

    from agentlab.core.session.service import request_tool_approval

    svc = services(tmp_path)
    begun, finish = asyncio.Event(), asyncio.Event()

    class BlockingHub(FakeHub):
        async def call(self, tool, args):
            begun.set()
            await finish.wait()
            return await super().call(tool, args)

    hub = svc.mcp = BlockingHub()
    project = svc.projects.create('project', 'test', str(tmp_path)) if project_chat else None
    prefix = f'/projects/{project.id}' if project else ''
    async with AsyncClient(transport=ASGITransport(app=create_app(svc)), base_url='http://test') as client:
        thread = (await client.post(prefix + '/threads', json={'title': 'write'})).json()
        approval = request_tool_approval(svc, project.id if project else None, thread['id'], WRITE.qualified, {})
        url = f"{prefix}/threads/{thread['id']}/tool-approvals/{approval['approval_id']}"
        task = asyncio.create_task(client.post(url, json={'decision': 'allow'}))
        await asyncio.wait_for(begun.wait(), 2)
        try:
            assert svc.store.records('mcp_approval')[0]['status'] == 'executing'
            assert (await client.delete(f"{prefix}/threads/{thread['id']}")).status_code == 409
            if project:
                assert (await client.delete(prefix)).status_code == 409
            assert (await client.post(url, json={'decision': 'allow'})).status_code == 409
            assert (await client.post(f"{prefix}/threads/{thread['id']}/messages", json={'text': 'hello'})).status_code == 409
        finally:
            finish.set()
        assert (await task).json() == {'status': 'done'}
        assert len(hub.calls) == 1
        messages = (await client.get(prefix + '/threads')).json()[0]['messages']
        assert any(m['kind'] == 'tool_result' for m in messages)
        assert (await client.delete(prefix if project else f"/threads/{thread['id']}")).status_code == 200


async def test_interrupted_tool_is_not_replayed_and_can_be_reconciled(tmp_path: Path) -> None:
    from httpx import ASGITransport, AsyncClient

    from agentlab.core.session.service import request_tool_approval

    svc = services(tmp_path)
    begun = asyncio.Event()

    class InterruptedHub(FakeHub):
        async def call(self, tool, args):
            self.calls.append((tool.name, args))
            begun.set()
            await asyncio.Event().wait()

    hub = svc.mcp = InterruptedHub()
    async with AsyncClient(transport=ASGITransport(app=create_app(svc)), base_url='http://test') as client:
        thread = (await client.post('/threads', json={'title': 'write'})).json()
        approval = request_tool_approval(svc, None, thread['id'], WRITE.qualified, {})
        url = f"/threads/{thread['id']}/tool-approvals/{approval['approval_id']}"
        task = asyncio.create_task(client.post(url, json={'decision': 'allow'}))
        await asyncio.wait_for(begun.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert svc.store.records('mcp_approval')[0]['status'] == 'unknown_outcome'
        assert (await client.post(url, json={'decision': 'allow'})).status_code == 409
        assert (await client.post(url, json={'decision': 'deny'})).status_code == 409
        assert (await client.post(url, json={'decision': 'confirm_done'})).json() == {'status': 'confirmed_done'}
        assert len(hub.calls) == 1


@pytest.mark.parametrize('decision', ['confirm_done', 'close_unknown'])
def test_restart_recovers_stale_execution_without_replaying(tmp_path: Path, decision: str) -> None:
    from agentlab.core.session.service import request_tool_approval

    svc = services(tmp_path)
    svc.mcp = hub = FakeHub()
    with TestClient(create_app(svc)) as client:
        thread = client.post('/threads', json={'title': 'write'}).json()
    approval = request_tool_approval(svc, None, thread['id'], WRITE.qualified, {})
    record = svc.store.records('mcp_approval')[0]
    record['status'] = 'executing'
    svc.store.put_record('mcp_approval', record['id'], record)
    with TestClient(create_app(svc)) as client:
        url = f"/threads/{thread['id']}/tool-approvals/{approval['approval_id']}"
        assert client.get(f"/threads/{thread['id']}/tool-approvals").json()[0]['status'] == 'unknown_outcome'
        assert client.post(url, json={'decision': 'allow'}).status_code == 409
        assert client.post(url, json={'decision': decision}).status_code == 200
        assert client.post(url, json={'decision': decision}).status_code == 409
        assert client.get("/threads/other/tool-approvals").status_code == 404
    assert hub.calls == []


def test_recovery_does_not_mark_another_process_live_call_unknown(tmp_path: Path) -> None:
    from agentlab.core.session.service import request_tool_approval
    from agentlab.core.session.tool_approvals import recover_tool_approvals

    svc = services(tmp_path)
    with TestClient(create_app(svc)) as client:
        thread = client.post('/threads', json={'title': 'write'}).json()
    approval = request_tool_approval(svc, None, thread['id'], WRITE.qualified, {})
    record = svc.store.records('mcp_approval')[0]
    record['status'] = 'executing'
    svc.store.put_record('mcp_approval', record['id'], record)
    with svc.store.lock_run('turn:' + thread['id']), svc.store.lock_run('tool-approval:' + approval['approval_id']):
        recover_tool_approvals(svc)
        assert svc.store.records('mcp_approval')[0]['status'] == 'executing'


def test_remote_transport_error_is_unknown_and_never_replayed(tmp_path: Path) -> None:
    from agentlab.core.session.service import request_tool_approval

    svc = services(tmp_path)

    class LostResponseHub(FakeHub):
        async def call(self, tool, args):
            self.calls.append((tool.name, args))
            raise ConnectionError('response lost after remote write')

    svc.mcp = hub = LostResponseHub()
    with TestClient(create_app(svc)) as client:
        thread = client.post('/threads', json={'title': 'write'}).json()
        approval = request_tool_approval(svc, None, thread['id'], WRITE.qualified, {})
        url = f"/threads/{thread['id']}/tool-approvals/{approval['approval_id']}"
        assert client.post(url, json={'decision': 'allow'}).json() == {'status': 'unknown_outcome'}
        assert client.post(url, json={'decision': 'allow'}).status_code == 409
        assert client.post(url, json={'decision': 'close_unknown'}).json() == {'status': 'closed_unknown'}
    assert len(hub.calls) == 1


def test_success_followed_by_storage_failure_cannot_replay(tmp_path: Path, monkeypatch) -> None:
    from agentlab.core.session.service import request_tool_approval

    svc = services(tmp_path)
    svc.mcp = hub = FakeHub()
    save = svc.store.put_record

    def fail_finish(kind, key, data):
        if kind == 'mcp_approval' and data.get('status') == 'done':
            raise OSError('storage unavailable after remote write')
        return save(kind, key, data)

    with TestClient(create_app(svc), raise_server_exceptions=False) as client:
        thread = client.post('/threads', json={'title': 'write'}).json()
        approval = request_tool_approval(svc, None, thread['id'], WRITE.qualified, {})
        url = f"/threads/{thread['id']}/tool-approvals/{approval['approval_id']}"
        monkeypatch.setattr(svc.store, 'put_record', fail_finish)
        assert client.post(url, json={'decision': 'allow'}).status_code == 500
        assert svc.store.records('mcp_approval')[0]['status'] == 'executing'
        monkeypatch.setattr(svc.store, 'put_record', save)
    with TestClient(create_app(svc)) as restarted:
        assert restarted.post(url, json={'decision': 'allow'}).status_code == 409
        assert svc.store.records('mcp_approval')[0]['status'] == 'unknown_outcome'
    assert len(hub.calls) == 1


def test_recovery_persists_outcome_even_when_conversation_is_full(tmp_path: Path) -> None:
    from agentlab.core.conversation import Conversation, Message
    from agentlab.core.session.service import request_tool_approval

    svc = services(tmp_path)
    svc.mcp = FakeHub()
    thread = Conversation(project_id=None, title='full', messages=[Message(author='user', text='m') for _ in range(999)])
    svc.store.put_record('thread', thread.id, thread.model_dump(mode='json'))
    request_tool_approval(svc, None, thread.id, WRITE.qualified, {})
    record = svc.store.records('mcp_approval')[0]
    record['status'] = 'executing'
    svc.store.put_record('mcp_approval', record['id'], record)
    with TestClient(create_app(svc)) as client:
        assert svc.store.records('mcp_approval')[0]['status'] == 'unknown_outcome'
        assert 'will not be run again' in svc.store.records('mcp_approval')[0]['result_text']
        assert client.post(f'/threads/{thread.id}/tool-approvals/{record["id"]}', json={'decision': 'confirm_done'}).status_code == 200
