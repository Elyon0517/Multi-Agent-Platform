"""Real native SDKs + PostgreSQL + process interruption. Explicit opt-in; costs API usage.

AGENTLAB_LIVE_SDK=1 AGENTLAB_TEST_DATABASE_URL=<disposable-db> pytest -s tests/live/test_live_sdk_handoff.py
The fixture deliberately limits the first Coder delivery so the real Reviewer must discover the upper-bound gap.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("AGENTLAB_LIVE_SDK") != "1", reason="real native SDK calls require opt-in"
)


def test_real_sdk_review_repair_and_interrupted_delivery_resume(tmp_path):
    from agentlab.adapters.store.postgres import PostgresStore

    assert os.environ.get("AGENTLAB_TEST_DATABASE_URL"), "use a disposable PostgreSQL database"
    root = Path(__file__).resolve().parents[2]
    command = [sys.executable, str(root / "scripts/check_sdk_handoff.py")]
    first = subprocess.run([*command, "start", str(tmp_path)], cwd=root, capture_output=True, text=True, timeout=660)
    assert first.returncode == 86, first.stdout + first.stderr
    store = PostgresStore(os.environ["AGENTLAB_TEST_DATABASE_URL"])
    run_id = json.loads((tmp_path / "run.json").read_text())["run_id"]
    before = [r for r in store.records("harness_invocation") if r["run_id"] == run_id]
    assert len(before) == 1 and before[0]["status"] == "completed" and before[0]["backend"] == "codex"
    intents = [r for r in store.records("edit_operation") if r["run_id"] == run_id]
    assert len(intents) == 1
    assert [r["status"] for r in intents[0]["files"]] == ["applied", "pending"]
    second = subprocess.run([*command, "resume", str(tmp_path)], cwd=root, capture_output=True, text=True, timeout=660)
    assert second.returncode == 0, second.stdout + second.stderr
    result = json.loads((tmp_path / "result.json").read_text())
    assert result["status"] == "DONE"
    coder = [r for r in result["invocations"] if r["backend"] == "codex"]
    reviewer = [r for r in result["invocations"] if r["backend"] == "claude"]
    assert len(coder) == len(reviewer) == 2
    assert before[0]["id"] in {r["id"] for r in coder}
    assert len({r["base_revision"] for r in reviewer}) == 2
    assert all(r["status"] == "completed" and r["session_id"] for r in result["invocations"])
    print(second.stdout)


def test_real_sdk_running_interruption_is_not_replayed(tmp_path):
    root = Path(__file__).resolve().parents[2]
    command = [sys.executable, str(root / "scripts/check_sdk_handoff.py")]
    assert os.environ.get("AGENTLAB_TEST_DATABASE_URL"), "use a disposable PostgreSQL database"
    first = subprocess.run(
        [*command, "start-sdk-interruption", str(tmp_path)], cwd=root, capture_output=True, text=True, timeout=660
    )
    assert first.returncode == 87, first.stdout + first.stderr
    second = subprocess.run(
        [*command, "check-sdk-interruption", str(tmp_path)], cwd=root, capture_output=True, text=True, timeout=60
    )
    assert second.returncode == 0, second.stdout + second.stderr
    result = json.loads((tmp_path / "unknown_interruption.json").read_text())
    assert result["interrupted_call"] and result["unknown_writer_not_replayed"]
    assert result["original_files_unchanged"] and result["session_id"] and result["turn_id"]
