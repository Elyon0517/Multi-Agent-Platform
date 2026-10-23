"""Opt-in real SDK handoff fixture. Runs only against an explicitly supplied disposable database.

See tests/live/test_live_sdk_handoff.py. No SDK responses/verdicts are fabricated.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from agentlab.adapters.gates.config_gate import ConfigGate
from agentlab.adapters.sandbox.local import LocalSandbox
from agentlab.bootstrap import build_services, project_gate_cfg
from agentlab.core.loop.hooks import NoHooks
from agentlab.core.schemas import RunStatus
from agentlab.secrets import EnvFile
from agentlab.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


class FixtureHooks(NoHooks):
    async def context_for(self, run, role, inp):
        if role == "coder" and inp.iteration == 1:
            return {
                "integration_fixture": (
                    "Controlled integration fixture, initial delivery ONLY: implement clamp(n) as max(0, n), "
                    "deliberately leaving the upper bound for the subsequent independent review. "
                    "Update README.md to describe this initial implementation. Do not modify test_clamp.py. "
                    "On a subsequent delivery follow reviewer findings and the full goal instead."
                )
            }
        return {}


def services(directory):
    values = EnvFile(ROOT / ".env").read()
    # Explicit test-only mapping: exercise the configured Anthropic endpoint through the native SDK.
    # Production SDK authentication remains independently configured.
    os.environ.setdefault("ANTHROPIC_API_KEY", values.get("AGENTLAB_ANTHROPIC_API_KEY", ""))
    os.environ.setdefault(
        "ANTHROPIC_BASE_URL", values.get("AGENTLAB_ANTHROPIC_BASE_URL", "").rstrip("/").removesuffix("/v1")
    )
    dsn = os.environ["AGENTLAB_TEST_DATABASE_URL"]
    svc = build_services(
        Settings(
            config_dir=ROOT / "config",
            data_dir=directory / "data",
            env_file=ROOT / ".env",
            runtime="sdk",
            sandbox="local",
            store_backend="postgres",
            database_url=dsn,
        )
    )
    svc.cfg.harness.codex_model = os.environ.get("AGENTLAB_SDK_CODEX_MODEL")
    svc.cfg.harness.claude_model = os.environ.get("AGENTLAB_SDK_CLAUDE_MODEL", svc.cfg.models.aliases["strong"].model)
    return svc


async def main():
    phase, path = sys.argv[1:]
    directory = Path(path).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    svc = services(directory)
    if phase in {"start", "start-sdk-interruption"}:
        source = directory / "workspace"
        source.mkdir(exist_ok=True)
        (source / "clamp.py").write_text("def clamp(n):\n    return n\n")
        (source / "README.md").write_text("Unimplemented clamp helper.\n")
        (source / "test_clamp.py").write_text(
            "import unittest\nfrom clamp import clamp\n\n"
            "class TestClamp(unittest.TestCase):\n"
            "    def test_lower(self): self.assertEqual(clamp(-3), 0)\n"
            "    def test_middle(self): self.assertEqual(clamp(4), 4)\n"
        )
        subprocess.run(["git", "init", "--quiet", str(source)], check=True)
        driver = svc.driver(source, "sdk")
        driver.hooks = FixtureHooks()
        driver.gate = ConfigGate(
            project_gate_cfg([f"{sys.executable} -m unittest -q"]), LocalSandbox(), lambda text: svc.blobs.put(text)[0]
        )
        driver.recovery_options["gate"] = driver.gate.cfg.model_dump(mode="json")
        await driver.workspace.ensure_repo()
        run = await driver.create_async(
            "Implement clamp(n) to clamp integers to the inclusive range [0, 10]. "
            "Update README.md. Keep test_clamp.py unchanged. Full acceptance: clamp(-3)=0, clamp(4)=4, clamp(18)=10. "
            "The independent review must check the upper bound even though the objective Gate only covers lower/middle."
        )
        (directory / "run.json").write_text(json.dumps({"run_id": run.id}))
        apply = driver.workspace.apply_edits
        count = 0

        def interrupt_second(edits, expected_hashes=None):
            nonlocal count
            count += 1
            if count == 2:
                print("INTERRUPT: completed SDK result; first file applied; second file pending", flush=True)
                os._exit(86)
            return apply(edits, expected_hashes)

        if phase == "start-sdk-interruption":
            native_run = driver.runtime.codex.run

            async def interrupt_live_turn(**kwargs):
                persist = kwargs["update"]

                def after_persist(data):
                    persist(data)
                    if data.get("turn_id"):
                        print("INTERRUPT: real SDK turn started, completion unknown", flush=True)
                        os._exit(87)

                return await native_run(**{**kwargs, "update": after_persist})

            driver.runtime.codex.run = interrupt_live_turn
        else:
            driver.workspace.apply_edits = interrupt_second
        print("START", run.id, flush=True)
    else:
        run_id = json.loads((directory / "run.json").read_text())["run_id"]
        driver = svc.restore_driver(run_id)
        driver.hooks = FixtureHooks()
        run = svc.store.get_run(run_id)
        if phase == "check-sdk-interruption":
            before = [r for r in svc.store.records("harness_invocation") if r["run_id"] == run.id]
            assert len(before) == 1 and before[0]["status"] == "running" and before[0]["turn_id"]
            run = await driver.run(run.id)
            assert run.paused_reason == "interrupted_call"
            driver.decide(run.id, "approve")
            run = await driver.run(run.id)
            approval = svc.store.pending_approval(run.id)
            assert approval.payload["error_kind"] == "harness_interrupted_requires_replan"
            after = [r for r in svc.store.records("harness_invocation") if r["run_id"] == run.id]
            assert [r["id"] for r in before] == [r["id"] for r in after]
            assert (driver.workspace.root / "clamp.py").read_text() == "def clamp(n):\n    return n\n"
            assert not [r for r in svc.store.records("edit_operation") if r["run_id"] == run.id]
            (directory / "unknown_interruption.json").write_text(
                json.dumps(
                    {
                        "run_id": run.id,
                        "interrupted_call": True,
                        "unknown_writer_not_replayed": True,
                        "original_files_unchanged": True,
                        "invocation_id": before[0]["id"],
                        "session_id": before[0]["session_id"],
                        "turn_id": before[0]["turn_id"],
                    },
                    indent=2,
                )
            )
            driver.decide(run.id, "abort", by="sdk-integration-fixture")
            print(
                "PASS: active real SDK interruption paused; unknown execution not replayed; files unchanged", flush=True
            )
            return 0
        if run.status == RunStatus.WAITING_HUMAN:
            print("PAUSED", run.paused_reason, flush=True)
            # Only acknowledge the existing interrupted-call control point, never failures/signoff automatically.
            if run.paused_reason == "interrupted_call":
                driver.decide(run.id, "approve")
    async with asyncio.timeout(600):
        run = await driver.run(run.id)
    iterations = svc.store.iterations(run.id)
    invocations = [r for r in svc.store.records("harness_invocation") if r["run_id"] == run.id]
    attempts = [r for r in svc.store.records("attempt") if r.get("run_id") == run.id]
    result = {
        "run_id": run.id,
        "status": run.status.value,
        "paused_reason": run.paused_reason,
        "iterations": [i.model_dump(mode="json") for i in iterations],
        "invocations": [
            {
                k: r.get(k)
                for k in [
                    "id",
                    "role",
                    "backend",
                    "status",
                    "session_id",
                    "turn_id",
                    "base_revision",
                    "sdk_version",
                    "model",
                    "usage",
                ]
            }
            for r in invocations
        ],
        "attempts": [{k: a.get(k) for k in ["role", "status", "error_kind", "backend"]} for a in attempts],
        "steps": [
            {"role": s.role, "model": s.model, "routing_reason": s.routing_reason} for s in svc.store.steps(run.id)
        ],
        "edits": [r for r in svc.store.records("edit_operation") if r["run_id"] == run.id],
    }
    (directory / "result.json").write_text(json.dumps(result, indent=2))
    print("RESULT", run.status.value, run.paused_reason, "iterations", len(iterations), flush=True)
    if run.paused_reason != "signoff":
        approval = svc.store.pending_approval(run.id)
        print("DETAIL", json.dumps(approval.payload if approval else {}), flush=True)
        return 2
    assert len([r for r in invocations if r["backend"] == "codex"]) == 2, (
        "Expected initial code + one repair; no replay"
    )
    assert len([r for r in invocations if r["backend"] == "claude"]) == 2
    assert iterations[0].verdicts[0].verdict == "REQUEST_CHANGES"
    assert iterations[-1].verdicts[0].verdict == "APPROVE"
    assert all(i.gate_result.passed and i.gate_result.revision_id == i.revision_id for i in iterations)
    assert len({i.revision_id for i in iterations}) == 2
    assert all(f["path"] in {"README.md", "clamp.py"} for op in result["edits"] for f in op["files"])
    approval = svc.store.pending_approval(run.id)
    assert approval.reason == "signoff" and approval.payload["revision_id"] == iterations[-1].revision_id
    result["signoff_evidence"] = {
        "revision_id": approval.payload["revision_id"],
        "diff_ref": approval.payload.get("diff_ref"),
    }
    gates = []
    for artifact in svc.store.artifacts(run.id, "gate"):
        gate = json.loads(svc.blobs.get(artifact.content_ref))
        gates.append({"mode": gate["mode"], "passed": gate["passed"], "revision_id": artifact.revision_id})
    assert gates[-1]["mode"] == "full" and gates[-1]["passed"]
    assert gates[-1]["revision_id"] == iterations[-1].revision_id
    result["gate_evidence"] = gates
    ledger = [row for row in svc.store.usage_entries() if row.get("ref_id") == run.id]
    assert len([row for row in ledger if row["role"] == "coder"]) == 2
    assert len([row for row in ledger if row["role"] == "correctness-reviewer"]) == 2
    result["native_call_counts"] = {"coder": 2, "correctness-reviewer": 2}
    scope = {}
    exec((driver.workspace.root / "clamp.py").read_text(), scope)
    assert [scope["clamp"](n) for n in [-3, 4, 18]] == [0, 4, 10]
    run = driver.decide(run.id, "approve", by="sdk-integration-fixture")
    assert run.status == RunStatus.DONE
    result["status"] = run.status.value
    result["paused_reason"] = run.paused_reason
    (directory / "result.json").write_text(json.dumps(result, indent=2))
    print(
        "DONE: real code, Gate, real review, repair, fresh revision, signoff; interrupted result not replayed",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
