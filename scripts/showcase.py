"""Visual showcase: scripted multi-agent runs for watching the Office floor.

Starts the real API (port 8765) with real routing, Driver, Gate and event stream; only the
model replies are scripted, with delays so every transition is visible. Model names come from
config/models.yaml, so the floor shows the actual Claude / GPT switch per agent.

    uv run python scripts/showcase.py                 # all scenarios, auto-decides approvals
    uv run python scripts/showcase.py --only S2,S5    # selected scenarios
    uv run python scripts/showcase.py --manual        # you click approve / reject / abort in the UI
    uv run python scripts/showcase.py --speed 2       # twice as fast

Then: cd ui && npm run dev, open http://localhost:5173/?follow=1 and just watch.
Stop any running `agentlab serve` first (same port). No real model is called; nothing is billed.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import socket
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn

import agentlab.adapters.runtime.anthropic as anthropic_runtime
import agentlab.adapters.runtime.raw as raw_runtime
from agentlab.adapters.runtime.raw import RawRuntime
from agentlab.api.app import create_app
from agentlab.bootstrap import build_services
from agentlab.core.llm.retry import Retryable
from agentlab.core.llm.structured import Completion
from agentlab.demo import seed_demo_workspace
from agentlab.settings import Settings
from agentlab.workspaces import evaluation_workspace_root

HOST = "127.0.0.1"

SCENARIOS: dict[str, dict[str, Any]] = {
    "S1": {
        "title": "Happy path: Claude builds, mixed panel reviews in parallel",
        "watch": "planner → coder (tool use = working) → Gate → 3 reviewers enter together, leave one by one",
    },
    "S2": {
        "title": "Gate fails, then a reviewer requests changes",
        "watch": "Gate turns red, coder returns; next round arch-reviewer asks for a docstring; third round signs off",
    },
    "S3": {
        "title": "Claude outage: planner falls back to GPT",
        "watch": "planner thinks longer (retries), finishes on the GPT root model; coder is back on Claude",
    },
    "S4": {
        "title": "Budget pause mid-batch",
        "watch": "3 reviewers enter, run pauses on budget → they must leave; budget raised → they come back",
    },
    "S5": {
        "title": "Reviewers contradict each other",
        "watch": "arbiter shows looping/escalation; human feedback resolves it; next round signs off",
    },
    "S6": {
        "title": "Coder writes outside the workspace",
        "watch": "coder pauses with workspace_escape and leaves; run is aborted, everyone idle",
    },
    "S7": {
        "title": "Oscillation: the same wrong fix twice",
        "watch": "Gate fails twice on an identical diff → oscillation escalation → aborted",
    },
}

state: dict[str, Any] = {"speed": 1.0, "budget": None}


def tag_of(text: str) -> str:
    return next((t for t in SCENARIOS if f"[{t}]" in text), "S1")


async def pause(seconds: float) -> None:
    await asyncio.sleep(seconds / state["speed"])


def reply(obj: dict[str, Any], tool_calls: list[dict[str, Any]] | None = None) -> Completion:
    return Completion(json.dumps(obj, ensure_ascii=False), 1400, 380, tool_calls)


GOOD = "def add(a, b):\n    return a + b\n"
DOCSTRING = 'def add(a, b):\n    """Add two numbers."""\n    return a + b\n'
WRONG = "def add(a, b):\n    return a * b\n"
VALIDATED = (
    'def add(a, b):\n    """Add two integers."""\n    if not isinstance(a, int) or not isinstance(b, int):\n'
    '        raise TypeError("integers only")\n    return a + b\n'
)


def coder_output(tag: str, inp: dict[str, Any]) -> dict[str, Any]:
    gate_failed = bool(inp.get("gate")) and not inp["gate"].get("passed", True)
    if tag == "S2":
        content = DOCSTRING if inp.get("instructions") else GOOD if gate_failed else WRONG
    elif tag == "S5":
        content = VALIDATED if inp.get("feedback") else GOOD
    elif tag == "S6":
        return {"edits": [{"path": "../outside-the-workspace.py", "content": "print('escape')\n"}]}
    elif tag == "S7":
        content = WRONG
    else:
        content = GOOD
    return {"edits": [{"path": "calc.py", "content": content}]}


def verdict(role: str, tag: str, inp: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    diff = inp.get("diff") or ""
    if tag == "S2" and role == "arch-reviewer" and '"""' not in diff:
        findings.append(
            {
                "severity": "major",
                "category": "arch",
                "file": "calc.py",
                "line": 1,
                "issue": "public function lacks a docstring",
                "confidence": 0.6,
            }
        )
    if tag == "S5" and "isinstance" not in diff and role in {"correctness-reviewer", "arch-reviewer"}:
        stance = "forbid" if role == "correctness-reviewer" else "require"
        findings.append(
            {
                "severity": "major",
                "category": "correctness",
                "file": "calc.py",
                "line": 2,
                "issue": f"{stance} input validation in add",
                "confidence": 0.65,
                "subject": "add-validation",
                "stance": stance,
            }
        )
    return {
        "reviewer_id": role,
        "verdict": "REQUEST_CHANGES" if findings else "APPROVE",
        "findings": findings,
        "summary": f"{role} reviewed the diff",
    }


DELAYS = {
    "planner": 2.5,
    "coder": 3.0,
    "correctness-reviewer": 3.0,
    "arch-reviewer": 5.5,
    "test-style-reviewer": 4.2,
    "supervisor": 2.0,
    "root": 2.0,
}


def scripted_chat(provider: str) -> Any:
    async def chat(**kwargs: Any) -> Completion:
        role = kwargs["system"].splitlines()[0].lstrip("# ").strip()
        title = kwargs["schema"].get("title", "")
        messages = kwargs["messages"]
        inp = json.loads(next(m["content"] for m in messages if m["role"] == "user"))
        tag = tag_of(inp.get("goal", ""))
        await pause(DELAYS.get(role, 2.0))
        if provider == "anthropic" and tag == "S3" and title == "Plan":
            raise Retryable("server_error_5xx")  # simulated Claude outage → fallback to GPT
        if title == "Plan":
            return reply(
                {
                    "summary": f"{inp['goal'][:60]} (planned on {kwargs['model']})",
                    "steps": ["inspect calc.py", "fix add", "keep tests unchanged"],
                    "acceptance_criteria": ["pytest passes"],
                }
            )
        if title == "CoderOutput":
            tools = kwargs.get("tools") or []
            if messages[-1]["role"] != "tool" and any(t["function"]["name"] == "workspace_read" for t in tools):
                call = {
                    "id": f"call_{time.time_ns()}",
                    "type": "function",
                    "function": {"name": "workspace_read", "arguments": json.dumps({"path": "calc.py"})},
                }
                return Completion("", 900, 40, [call])  # shows the coder "working" with a tool
            return reply(coder_output(tag, inp))
        if title == "Verdict":
            return reply(verdict(role, tag, inp))
        raise RuntimeError(f"showcase has no script for {role}/{title}")

    return chat


class SlowGate:
    """Real demo Gate (pytest), delayed so the Gate agent is visible on the floor."""

    def __init__(self, gate: Any) -> None:
        self._gate = gate

    def __getattr__(self, name: str) -> Any:
        return getattr(self._gate, name)

    async def run(self, workspace: Path, mode: Any) -> Any:
        await pause(2.0)
        return await self._gate.run(workspace, mode)


def build_app() -> Any:
    raw_runtime.OpenAICompatChat = lambda *a, **k: scripted_chat("openai")  # type: ignore[assignment,misc]
    anthropic_runtime.AnthropicChat = lambda *a, **k: scripted_chat("anthropic")  # type: ignore[assignment,misc]
    svc = build_services(Settings(store_backend="memory", runtime="fake", sandbox="local"))
    original = svc.driver

    def showcase_driver(
        workspace: Path, runtime: str | None = None, language: str | None = None, project_id: str | None = None
    ) -> Any:
        driver = original(workspace, "fake", "python", project_id)  # demo pytest Gate, no gateway needed
        if state["budget"] is not None:
            budget = driver.cfg.budget.model_copy(update={"default_run_budget_cents": state["budget"]})
            driver.cfg = driver.cfg.model_copy(update={"budget": budget})
        model_runtime = RawRuntime(driver.cfg, "http://showcase.gpt/v1", "showcase", ("http://showcase.claude/v1", "x"))
        driver.runtime = model_runtime
        driver.runtime_factory = lambda: model_runtime
        driver.gate = SlowGate(driver.gate)
        return driver

    svc.driver = showcase_driver  # type: ignore[method-assign]
    return create_app(svc)


async def decide(client: httpx.AsyncClient, run_id: str, reason: str, payload: dict[str, Any]) -> str:
    if reason == "signoff":
        body: dict[str, Any] = {"decision": "approve"}
    elif reason == "budget_exceeded":
        body = {"decision": "approve", "budget_cents": max(float(payload.get("required_budget_cents") or 0) * 2, 300)}
    elif reason in {"reviewer_conflict", "inconsistent_verdict"}:
        body = {"decision": "approve", "feedback": "Follow arch-reviewer: add input validation."}
    else:  # workspace_escape, oscillation_detected, execution_error ...
        body = {"decision": "abort"}
    (await client.post(f"/runs/{run_id}/decision", json=body)).raise_for_status()
    return str(body["decision"]) + (f" (budget→{body['budget_cents']:.0f}c)" if "budget_cents" in body else "")


async def play(client: httpx.AsyncClient, tag: str, manual: bool) -> str:
    spec = SCENARIOS[tag]
    print(f"\n━━ {tag}: {spec['title']}\n   watch: {spec['watch']}")
    state["budget"] = 30.0 if tag == "S4" else None
    workspace = seed_demo_workspace(Path(tempfile.mkdtemp(prefix=f"showcase-{tag}-", dir=evaluation_workspace_root())))
    created = await client.post(
        "/runs", json={"goal": f"[{tag}] fix calc.add so tests pass", "workspace": str(workspace)}
    )
    created.raise_for_status()
    run_id = created.json()["id"]
    seen: set[str] = set()
    deadline = time.monotonic() + 240 / state["speed"]
    while time.monotonic() < deadline:
        detail = (await client.get(f"/runs/{run_id}")).json()
        run, approval = detail["run"], detail["pending_approval"]
        if run["status"] in {"DONE", "CANCELLED"}:
            models = {s["role"]: s["model"] for s in detail["steps"]}
            print(f"   end: {run['status']} · {len(detail['steps'])} model calls · models {models}")
            return str(run["status"])
        if approval and approval["id"] not in seen:
            seen.add(approval["id"])
            print(f"   paused: {approval['reason']}")
            if manual:
                print("   → decide in the UI (approve / reject+feedback / abort)")
            else:
                await pause(4.0)  # leave the banner on screen for a moment
                print(f"   decided: {await decide(client, run_id, approval['reason'], approval['payload'])}")
        await asyncio.sleep(0.5)
    print("   ✗ timed out — the run is stuck; check the backend log")
    return "TIMEOUT"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", default=",".join(SCENARIOS))
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--manual", action="store_true")
    parser.add_argument("--gap", type=float, default=3.0, help="seconds between scenarios")
    parser.add_argument("--port", type=int, default=8765, help="the UI dev proxy expects 8765")
    args = parser.parse_args()
    state["speed"] = max(args.speed, 0.1)
    tags = [t.strip().upper() for t in args.only.split(",") if t.strip()]
    if unknown := [t for t in tags if t not in SCENARIOS]:
        raise SystemExit(f"unknown scenarios {unknown}; choose from {list(SCENARIOS)}")
    with socket.socket() as probe:
        if probe.connect_ex((HOST, args.port)) == 0:
            raise SystemExit(f"port {args.port} is busy — stop `agentlab serve` first")

    api = f"http://{HOST}:{args.port}"
    server = uvicorn.Server(uvicorn.Config(build_app(), host=HOST, port=args.port, log_level="warning"))
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.1)
    print(f"Showcase API on {api}. Open http://localhost:5173/?follow=1 (ui: npm run dev).")
    await asyncio.sleep(3)
    results: dict[str, str] = {}
    async with httpx.AsyncClient(base_url=api, timeout=30) as client:
        for tag in tags:
            results[tag] = await play(client, tag, args.manual)
            await asyncio.sleep(args.gap)
    print("\nSummary:", results)
    print("Server keeps running for inspection; press Ctrl+C to stop.")
    await serving


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
