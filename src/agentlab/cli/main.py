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


@app.command()
def ping() -> None:
    """Check each configured alias using the gateway's Chat Completions API."""
    import openai

    svc = build_services()
    url, key = svc.gateway()
    if not url or not key:
        typer.echo("Set AGENTLAB_LLM_BASE_URL and AGENTLAB_LLM_API_KEY in .env", err=True)
        raise typer.Exit(1)

    async def probe() -> bool:
        passed = True
        async with openai.AsyncOpenAI(base_url=url, api_key=key, timeout=45, max_retries=0) as client:
            for alias, model in svc.cfg.models.aliases.items():
                try:
                    result = await client.chat.completions.create(
                        model=model.model, temperature=0.0, max_tokens=64,
                        messages=[{"role": "user", "content": 'Return JSON only: {"ok": true}'}],
                        response_format={"type": "json_object"},
                    )
                    valid = json.loads(result.choices[0].message.content or "{}").get("ok") is True
                    usage = result.usage
                    good = valid and usage is not None
                    passed &= good
                    typer.echo(json.dumps({"alias": alias, "model": model.model, "ok": good,
                                           "tokens": usage.total_tokens if usage else None}))
                except Exception as exc:
                    passed = False
                    # Do not echo gateway exceptions: their payload may contain request secrets.
                    typer.echo(json.dumps({"alias": alias, "model": model.model, "ok": False,
                                           "error": type(exc).__name__,
                                           "status": getattr(exc, "status_code", None)}))
        return passed

    if not asyncio.run(probe()):
        raise typer.Exit(1)


@app.command()
def smoke(trials: Annotated[int, typer.Option(min=1, max=3)] = 3) -> None:
    """Run the fixed Python repair task on fresh workspaces; stop at human signoff."""
    import shutil

    from agentlab.core.loop.hooks import NoHooks
    from agentlab.core.schemas import GateMode

    svc = build_services()
    template = svc.cfg.root.parent / "evals" / "tasks" / "py-fix-add"
    root = svc.settings.data_dir / "smoke"
    root.mkdir(parents=True, exist_ok=True)

    async def evaluate() -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        for index in range(trials):
            workspace = Path(tempfile.mkdtemp(prefix="py-fix-add-", dir=root.resolve()))
            shutil.copytree(template, workspace, dirs_exist_ok=True)
            driver = svc.driver(workspace, "raw", "python")
            driver.hooks = NoHooks()  # isolate convergence from optional RAG/embedding calls
            await driver.workspace.ensure_repo()  # type: ignore[attr-defined]
            baseline = await driver.gate.run(workspace, GateMode.FAST)
            if baseline.passed or baseline.failed_at != "test":
                raise RuntimeError("smoke baseline must fail specifically at the tests")
            typer.echo(f"Trial {index + 1}/{trials}: baseline tests fail; starting real model loop", err=True)
            run = await driver.run(driver.create(
                "Fix calc.add so all tests pass. Preserve the tests and their assertions; "
                "support positive, negative and zero integer inputs. Keep changes minimal."
            ).id)
            diff = await driver.workspace.diff()
            checks = await driver.gate.run(workspace, GateMode.FULL)
            tests_unchanged = (workspace / "test_calc.py").read_bytes() == (template / "test_calc.py").read_bytes()
            result: dict[str, object] = {
                "trial": index + 1, "run_id": run.id, "workspace": str(workspace),
                "status": run.status, "reason": run.paused_reason,
                "signoff": run.status == RunStatus.WAITING_HUMAN and run.paused_reason == "signoff",
                "gate_passed": checks.passed, "tests_unchanged": tests_unchanged,
                "iterations": len(svc.store.iterations(run.id)),
                "tokens": run.tokens_in + run.tokens_out, "estimated_cost_cents": run.cost_cents,
            }
            result["passed"] = bool(result["signoff"] and checks.passed and tests_unchanged)
            results.append(result)
            (workspace.parent / f"{run.id}-diff.txt").write_text(diff)
            (workspace.parent / f"{run.id}-gate.json").write_text(checks.model_dump_json(indent=2))
            (workspace.parent / f"{run.id}-events.json").write_text(
                json.dumps([e.model_dump(mode="json") for e in svc.store.events(run.id)], indent=2)
            )
            (root / "results.json").write_text(json.dumps(results, indent=2))
            typer.echo(json.dumps(result))
        return results

    results = asyncio.run(evaluate())
    successes = sum(bool(r["passed"]) for r in results)
    typer.echo(f"Convergence: {successes}/{trials}; human approval remains pending.")
    if successes < min(2, trials):
        raise typer.Exit(1)
