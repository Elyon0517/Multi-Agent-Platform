import asyncio
from pathlib import Path

from agentlab.core.loop.hooks import NoHooks
from agentlab.core.schemas import RunStatus
from agentlab.demo import seed_demo_workspace
from tests.unit.test_memory_project import _svc


class SlowSummary(NoHooks):
    """Stands in for the Root summary written when a run pauses (a model call that can take many seconds)."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def on_waiting(self, run) -> None:
        self.started.set()
        await self.release.wait()


async def test_an_approval_can_be_decided_while_the_pause_summary_is_still_running(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    driver = svc.driver(seed_demo_workspace(tmp_path / "ws"), "fake", "python")
    hooks = driver.hooks = SlowSummary()
    await driver.workspace.ensure_repo()
    run = await driver.create_async("fix add")
    task = asyncio.create_task(driver.run(run.id))
    await asyncio.wait_for(hooks.started.wait(), 30)
    assert svc.store.get_run(run.id).status == RunStatus.WAITING_HUMAN

    decided = driver.decide(run.id, "approve")  # previously raised RunBusy until the summary finished
    assert decided.status == RunStatus.DONE

    hooks.release.set()
    await asyncio.wait_for(task, 30)
