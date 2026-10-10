"""Opt-in live check against the real gateways (costs a few cents).

    AGENTLAB_LIVE=1 uv run pytest -q -s tests/live

Requires both keys in .env, Colima running and the agentlab/gate-python image.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from agentlab.bootstrap import build_services
from agentlab.core.loop.hooks import NoHooks
from agentlab.core.schemas import RunStatus
from agentlab.settings import Settings
from agentlab.workspaces import evaluation_workspace_root

pytestmark = pytest.mark.skipif(
    os.environ.get("AGENTLAB_LIVE") != "1", reason="set AGENTLAB_LIVE=1 to call real models"
)

TASK = Path(__file__).resolve().parents[2] / "evals" / "tasks" / "py-fix-add"


async def test_real_gpt_and_claude_hand_off_one_task() -> None:
    svc = build_services(Settings(store_backend="memory", runtime="raw", sandbox="docker"))
    assert all(svc.gateway()) and all(svc.anthropic_gateway()), "both GPT and Claude credentials must be set"
    workspace = Path(tempfile.mkdtemp(prefix="live-provider-", dir=evaluation_workspace_root()))
    shutil.copytree(TASK, workspace, dirs_exist_ok=True)
    driver = svc.driver(workspace, "raw", "python")
    driver.hooks = NoHooks()
    try:
        async with asyncio.timeout(600):
            await driver.workspace.ensure_repo()  # type: ignore[attr-defined]
            run = await driver.run((await driver.create_async("Fix calc.add so all tests pass; keep tests unchanged.")).id)
        steps = svc.store.steps(run.id)
        providers = {s.role: driver.cfg.models.aliases[s.model_alias].provider for s in steps}
        print("\nrun", run.id, run.status, run.paused_reason, f"{run.cost_cents:.2f}c")
        for s in steps:
            print(f"  {s.role:<22} {providers[s.role]:<10} {s.model:<20} attempts={s.attempt_count} {s.routing_reason}")

        assert (run.status, run.paused_reason) == (RunStatus.WAITING_HUMAN, "signoff")
        assert {"planner", "coder", *driver.cfg.reviewer_roles} <= set(providers), "2-3+ agents must take part"
        assert set(providers.values()) == {"openai", "anthropic"}, "both vendors must actually answer"
        assert not any(s.routing_reason.startswith("fallback_from_") for s in steps), "no silent vendor fallback"
    finally:
        driver.workspace.close()  # type: ignore[attr-defined]
        shutil.rmtree(workspace, ignore_errors=True)
