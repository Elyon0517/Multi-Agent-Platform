from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Annotated

import typer

from agentlab.bootstrap import Services, build_services
from agentlab.core.loop.driver import Driver
from agentlab.core.schemas import Event, Run, RunStatus
from agentlab.demo import seed_demo_workspace

app = typer.Typer(no_args_is_help=True, add_completion=False)


def _print_event(e: Event) -> None:
    p = e.payload
    detail = {
        "run.status": lambda: f"{p['src']} -> {p['dst']}",
        "step.finished": lambda: f"{p['role']} via {p['model']} ({p['cost_cents']:.2f}c)",
        "artifact.created": lambda: f"{p['kind']} -> {p.get('to') or '-'}",
        "gate.finished": lambda: f"passed={p['passed']} {p.get('failed_at') or ''}",
        "arbiter.decision": lambda: f"{p['action']} {p['reason']}",
        "approval.requested": lambda: f"reason={p['reason']}",
    }.get(e.type, lambda: "")()
    typer.echo(f"{e.seq:>3} {e.type:<20} {e.actor:<22} {detail}")


async def _drive(svc: Services, driver: Driver, run: Run, auto_approve: bool) -> Run:
    run = await driver.run(run.id)
    while auto_approve and run.status == RunStatus.WAITING_HUMAN:
        run = driver.decide(run.id, "approve", by="auto")
        run = await driver.run(run.id)
    for e in svc.store.events(run.id):
        _print_event(e)
    return run


@app.command()
def run(
    goal: Annotated[str, typer.Argument()],
    workspace: Annotated[Path, typer.Option("--workspace", "-w")] = Path("."),
    runtime: Annotated[str | None, typer.Option(help="raw | adk | fake")] = None,
    language: Annotated[str | None, typer.Option()] = None,
    auto_approve: Annotated[bool, typer.Option()] = False,
) -> None:
    svc = build_services()
    driver = svc.driver(workspace, runtime, language)

    async def go() -> Run:
        await driver.workspace.ensure_repo()  # type: ignore[attr-defined]
        return await _drive(svc, driver, driver.create(goal), auto_approve)

    final = asyncio.run(go())
    typer.echo(json.dumps({"run_id": final.id, "status": final.status, "cost_cents": round(final.cost_cents, 3),
                           "paused_reason": final.paused_reason}))


@app.command()
def demo(auto_approve: Annotated[bool, typer.Option()] = True) -> None:
    ws = seed_demo_workspace(Path(tempfile.mkdtemp(prefix="agentlab-demo-")))
    typer.echo(f"workspace: {ws}")
    run("make test_add pass", workspace=ws, runtime="fake", language="python", auto_approve=auto_approve)


@app.command()
def config_check() -> None:
    cfg = build_services().cfg
    typer.echo(f"ok: {len(cfg.agents)} agents, {len(cfg.gates)} gates, aliases={sorted(cfg.models.aliases)}")
    for role, pol in cfg.model_policy.roles.items():
        typer.echo(f"  {role:<22} -> {pol.primary:<10} ({cfg.models.aliases[pol.primary].model})")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    uvicorn.run("agentlab.api.app:create_app", factory=True, host=host, port=port)
