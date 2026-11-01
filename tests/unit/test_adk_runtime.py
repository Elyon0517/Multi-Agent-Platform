"""The ADK runtime must be indistinguishable from the raw runtime at the gateway and in accounting.

Each test feeds the same scripted gateway replies to StructuredCaller (raw) and AdkCaller (ADK) and
compares what the gateway received, which tools ran, what was recorded and what came back.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("google.adk")

from agentlab.adapters.runtime.adk import AdkCaller, AdkRuntime
from agentlab.bootstrap import AdkUnavailable
from agentlab.core.config import AppConfig
from agentlab.core.conversation import RootTurn
from agentlab.core.llm.retry import Retryable
from agentlab.core.llm.structured import Completion, StructuredCaller
from agentlab.core.llm.tools import tool_spec
from agentlab.core.ports import RunContext
from agentlab.core.schemas import AgentInput, Plan, Run, Usage
from agentlab.settings import Settings
from tests.unit.test_memory_project import _svc

SPECS = [tool_spec("file_list", "List files", {})]


def _call(call_id: str, arguments: str = "{}") -> dict[str, Any]:
    return {"id": call_id, "type": "function", "function": {"name": "file_list", "arguments": arguments}}


def _quick(cfg: AppConfig, retries: int = 1) -> AppConfig:
    cfg = cfg.model_copy(deep=True)
    cfg.retry.llm_call.backoff_base_s = 0
    cfg.retry.llm_call.num_retries = retries
    return cfg


async def _both(cfg: AppConfig, role: str, output_type: Any, script: list[Any], execute: Any = None,
                specs: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for name, caller_type in (("raw", StructuredCaller), ("adk", AdkCaller)):
        chat = AsyncMock(side_effect=list(script))
        tool = AsyncMock(side_effect=execute) if execute else None
        run = Run(id="run-1", goal="g", workspace="/tmp", budget_unlimited=True)
        usage: list[Usage] = []
        tools: list[dict[str, Any]] = []
        attempts: list[dict[str, Any]] = []
        ctx = RunContext(run, lambda _: None, record_usage=usage.append, tool_specs=specs,
                         execute_tool=tool, record_tool=tools.append,
                         attempt_started=lambda data, log=attempts: log.append(data) or str(len(log)))
        outcome: Any
        try:
            outcome = await caller_type(cfg, chat).call(
                role, AgentInput(run_id=run.id, iteration=0, goal="g"), output_type, ctx)
        except Exception as exc:
            outcome = exc
        seen[name] = {"outcome": outcome, "calls": [c.kwargs for c in chat.call_args_list], "usage": usage,
                      "tools": tools, "executed": tool.call_args_list if tool else [], "attempts": attempts}
    return seen


def _assert_same_gateway_traffic(seen: dict[str, dict[str, Any]]) -> None:
    raw, adk = seen["raw"], seen["adk"]
    assert len(raw["calls"]) == len(adk["calls"])
    for r, a in zip(raw["calls"], adk["calls"], strict=True):
        assert a["system"].startswith(r["system"])  # ADK appends one identity line
        assert {k: v for k, v in a.items() if k != "system"} == {k: v for k, v in r.items() if k != "system"}
    assert raw["usage"] == adk["usage"] and raw["tools"] == adk["tools"] and raw["executed"] == adk["executed"]
    assert [x["alias"] for x in raw["attempts"]] == [x["alias"] for x in adk["attempts"]]


async def test_tool_loop_repair_and_retry_match_raw(tmp_path: Path) -> None:
    final = RootTurn(intent="answer", reply="done").model_dump_json()
    thinking = [{"type": "thinking", "thinking": "t", "signature": "s"},
                {"type": "tool_use", "id": "call-1", "name": "file_list", "input": {}}]
    script = [
        Retryable("rate_limit_429"),
        Completion("", 10, 5, [_call("call-1")], provider_content=thinking),
        Completion("", 10, 5, [_call("call-2", "not json")]),
        Completion("oops", 10, 5),
        Completion(final, 10, 5),
    ]
    seen = await _both(_quick(_svc(tmp_path).cfg), "root", RootTurn, script,
                       execute=lambda name, args: ["a.py"], specs=SPECS)

    _assert_same_gateway_traffic(seen)
    raw, adk = seen["raw"]["outcome"], seen["adk"]["outcome"]
    assert adk.output == raw.output and adk.output.reply == "done"
    assert (adk.alias, adk.model, adk.usage, adk.attempts, adk.retry_reasons, adk.routing_reason) == (
        raw.alias, raw.model, raw.usage, raw.attempts, raw.retry_reasons, raw.routing_reason)
    assert "structured_output_invalid" in adk.retry_reasons and "rate_limit_429" in adk.retry_reasons
    replay = seen["adk"]["calls"][2]["messages"]
    assert replay[1]["_anthropic_content"] == thinking  # signed thinking survives the ADK round trip
    assert json.loads(replay[2]["content"]) == ["a.py"]  # non-object tool result reaches the model unwrapped
    assert json.loads(seen["adk"]["calls"][3]["messages"][4]["content"]) == {"error": "JSONDecodeError"}


async def test_alias_fallback_matches_raw(tmp_path: Path) -> None:
    plan = Plan(summary="s", steps=["a"], acceptance_criteria=["b"]).model_dump_json()
    seen = await _both(_quick(_svc(tmp_path).cfg, retries=0), "planner", Plan,
                       [Retryable("server_error_5xx"), Completion(plan, 3, 2)])

    _assert_same_gateway_traffic(seen)
    raw, adk = seen["raw"]["outcome"], seen["adk"]["outcome"]
    assert adk.routing_reason == raw.routing_reason == "fallback_from_strong"
    assert (adk.alias, adk.model, adk.usage) == (raw.alias, raw.model, raw.usage)


async def test_worker_permission_error_stops_the_agent_like_raw(tmp_path: Path) -> None:
    def denied(name: str, args: dict[str, Any]) -> Any:
        raise PermissionError("not granted")

    seen = await _both(_quick(_svc(tmp_path).cfg), "coder", Plan, [Completion("", 1, 1, [_call("call-1")])],
                       execute=denied, specs=SPECS)

    _assert_same_gateway_traffic(seen)
    assert isinstance(seen["adk"]["outcome"], PermissionError)
    assert seen["adk"]["tools"][-1]["status"] == "failed"


async def test_tool_calls_without_tools_are_rejected_like_raw(tmp_path: Path) -> None:
    seen = await _both(_quick(_svc(tmp_path).cfg), "summarizer", Plan, [Completion("", 1, 1, [_call("call-1")])])

    assert str(seen["adk"]["outcome"]) == str(seen["raw"]["outcome"]) == "unexpected_tool_calls"


def test_services_build_adk_on_the_raw_gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc(tmp_path)
    monkeypatch.setattr(svc, "gateway", lambda: ("http://gpt.test/v1", "k"))
    assert isinstance(svc.runtime("adk"), AdkRuntime)
    monkeypatch.setitem(__import__("sys").modules, "agentlab.adapters.runtime.adk", None)
    with pytest.raises(AdkUnavailable):
        svc.runtime("adk")


async def test_review_panel_is_one_adk_invocation_with_raw_partial_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agentlab.adapters.runtime.anthropic as anthropic_runtime
    import agentlab.adapters.runtime.raw as raw_runtime
    from agentlab.adapters.runtime.raw import RawRuntime
    from agentlab.core.llm.retry import ParallelFailure, RetriesExhausted
    from agentlab.core.schemas import Verdict

    cfg = _quick(_svc(tmp_path).cfg, retries=0)
    reviewers = ["correctness-reviewer", "arch-reviewer", "test-style-reviewer"]
    traffic: dict[str, list[dict[str, Any]]] = {}

    async def chat(**kwargs: Any) -> Completion:
        role = json.loads(kwargs["messages"][0]["content"])["goal"]
        traffic.setdefault(role, []).append({k: v for k, v in kwargs.items() if k != "system"})
        if role == "arch-reviewer":
            raise Retryable("server_error_5xx")
        if role == "test-style-reviewer" and len(traffic[role]) == 1:
            return Completion("oops", 4, 2)
        return Completion(json.dumps({"reviewer_id": role, "verdict": "APPROVE", "findings": [], "summary": "ok"}),
                          4, 2)

    monkeypatch.setattr(raw_runtime, "OpenAICompatChat", lambda *a, **k: chat)
    monkeypatch.setattr(anthropic_runtime, "AnthropicChat", lambda *a, **k: chat)
    raw = RawRuntime(cfg, "http://gpt.test/v1", "k", ("http://claude.test/v1", "k"))
    invocations = 0
    invoke = AdkCaller._invoke

    async def counted(self: AdkCaller, root: Any) -> None:
        nonlocal invocations
        invocations += 1
        await invoke(self, root)

    monkeypatch.setattr(AdkCaller, "_invoke", counted)
    seen = {}
    for name, runtime in (("raw", raw), ("adk", AdkRuntime(cfg, raw.chat))):
        traffic.clear()
        run = Run(id="run-1", goal="g", workspace="/tmp", budget_unlimited=True)
        inputs = {r: AgentInput(run_id=run.id, iteration=0, goal=r) for r in reviewers}
        with pytest.raises(ParallelFailure) as failure:
            await runtime.run_parallel(inputs, Verdict, RunContext(run, lambda _: None))
        seen[name] = (failure.value, {r: list(calls) for r, calls in traffic.items()})

    (raw_failure, raw_traffic), (adk_failure, adk_traffic) = seen["raw"], seen["adk"]
    assert invocations == 1  # the whole panel ran as one ADK Workflow invocation
    assert isinstance(adk_failure.cause, RetriesExhausted) and type(adk_failure.cause) is type(raw_failure.cause)
    assert [(r.role, r.output, r.alias, r.attempts, r.retry_reasons) for r in adk_failure.results] == [
        (r.role, r.output, r.alias, r.attempts, r.retry_reasons) for r in raw_failure.results]
    assert [r.role for r in adk_failure.results] == ["correctness-reviewer", "test-style-reviewer"]
    # Each reviewer saw only its own input, repair and history: branch isolation matches raw's separate calls.
    assert adk_traffic == raw_traffic


def test_settings_toggle_makes_adk_the_default_for_new_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    import agentlab.bootstrap as bootstrap
    from agentlab.api.app import create_app

    svc = _svc(tmp_path)
    monkeypatch.setattr(svc, "gateway", lambda: ("http://gpt.test/v1", "k"))
    with TestClient(create_app(svc)) as c:
        assert c.get("/settings/runtime").json() == {"runtime": "fake", "adk_installed": True}
        assert c.put("/settings/runtime", json={"runtime": "adk"}).json()["runtime"] == "adk"
        assert isinstance(svc.runtime(), AdkRuntime)
        assert Settings(_env_file=tmp_path / ".env").runtime == "adk"  # type: ignore[call-arg]  # survives a restart
        assert c.put("/settings/runtime", json={"runtime": "sdk"}).status_code == 422
        assert c.put("/settings", json={"values": {"AGENTLAB_RUNTIME": "fake"}}).status_code == 422
        assert c.put("/settings/runtime", json={"runtime": "raw"}).json()["runtime"] == "raw"
        assert not isinstance(svc.runtime(), AdkRuntime)

        monkeypatch.setattr(bootstrap, "find_spec", lambda name: None)
        refused = c.put("/settings/runtime", json={"runtime": "adk"})
        assert refused.status_code == 400 and "uv sync --extra adk" in refused.text
        assert c.get("/settings/runtime").json() == {"runtime": "raw", "adk_installed": False}
