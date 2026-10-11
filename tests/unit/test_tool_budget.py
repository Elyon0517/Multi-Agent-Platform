from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agentlab.core.budget import BudgetExceeded, BudgetGuard
from agentlab.core.conversation import RootTurn
from agentlab.core.llm.structured import Completion, StructuredCaller
from agentlab.core.llm.tools import tool_spec
from agentlab.core.ports import RunContext
from agentlab.core.schemas import AgentInput, Run
from tests.unit.test_memory_project import _svc


def _tool_call(index: int) -> Completion:
    call = {"id": f"call-{index}", "type": "function", "function": {"name": "file_list", "arguments": "{}"}}
    return Completion("", 10, 5, [call])


def _ctx(run: Run, guard: BudgetGuard, execute: AsyncMock) -> RunContext:
    return RunContext(run, guard.check, record_usage=guard.record, reserve_budget=guard.reserve,
                      release_budget=guard.release, tool_specs=[tool_spec("file_list", "List files", {})],
                      execute_tool=execute)


async def test_tool_calls_are_not_capped_by_count(tmp_path: Path):
    cfg = _svc(tmp_path).cfg
    run = Run(goal="research", workspace=str(tmp_path), budget_cents=10_000)
    execute = AsyncMock(return_value=["a.py"])
    final = Completion(RootTurn(intent="answer", reply="done").model_dump_json(), 10, 5)
    chat = AsyncMock(side_effect=[*(_tool_call(i) for i in range(20)), final])
    result = await StructuredCaller(cfg, chat).call(
        "root", AgentInput(run_id=run.id, iteration=0, goal="research"), RootTurn,
        _ctx(run, BudgetGuard(run, 0.8, lambda _: None), execute),
    )
    assert result.output.reply == "done"
    assert execute.await_count == 20


async def test_runaway_tool_loop_stops_at_the_budget(tmp_path: Path):
    cfg = _svc(tmp_path).cfg
    run = Run(goal="research", workspace=str(tmp_path), budget_cents=2)
    execute = AsyncMock(return_value=["a.py"])
    chat = AsyncMock(side_effect=(_tool_call(i) for i in range(10_000)))
    with pytest.raises(BudgetExceeded):
        await StructuredCaller(cfg, chat).call(
            "root", AgentInput(run_id=run.id, iteration=0, goal="research"), RootTurn,
            _ctx(run, BudgetGuard(run, 0.8, lambda _: None), execute),
        )
    assert chat.await_count < 10_000
