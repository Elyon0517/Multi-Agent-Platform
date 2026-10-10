from __future__ import annotations

import asyncio
import os
import signal
import time
from contextlib import suppress
from pathlib import Path

from agentlab.core.ports import ExecResult

SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "DATABASE_URL")
GATE_ENV = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPYCACHEPREFIX": "/tmp/agentlab-pycache"}


def scrubbed_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not any(m in k.upper() for m in SECRET_MARKERS)}
    return {**env, **GATE_ENV}


async def run_argv(argv: list[str], cwd: Path | None, timeout_s: float, env: dict[str, str]) -> ExecResult:
    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    except FileNotFoundError as e:
        return ExecResult(127, "", str(e), int((time.monotonic() - started) * 1000))

    async def terminate() -> tuple[bytes, bytes]:
        # Kill descendants too: a child holding a pipe open must not stall cleanup.
        with suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        try:
            return await asyncio.wait_for(proc.communicate(), 5)
        except TimeoutError:
            return b"", b"Process cleanup exceeded 5s"

    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout_s)
        timed_out = False
    except TimeoutError:
        out, err = await terminate()
        timed_out = True
    except asyncio.CancelledError:
        await terminate()
        raise
    return ExecResult(
        exit_code=124 if timed_out else (proc.returncode or 0),
        stdout=out.decode(errors="replace"),
        stderr=err.decode(errors="replace"),
        duration_ms=int((time.monotonic() - started) * 1000),
        timed_out=timed_out,
    )


class LocalSandbox:
    async def exec(
        self, argv: list[str], cwd: Path, timeout_s: float, image: str | None = None, network: bool = False
    ) -> ExecResult:
        return await run_argv(argv, cwd, timeout_s, scrubbed_env())
