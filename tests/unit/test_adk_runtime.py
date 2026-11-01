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
