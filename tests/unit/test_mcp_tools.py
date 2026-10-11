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
