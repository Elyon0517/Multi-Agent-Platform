from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from agentlab.adapters.sandbox.local import GATE_ENV, run_argv, scrubbed_env
from agentlab.core.ports import ExecResult


@dataclass(frozen=True)
class DockerLimits:
    memory: str = "4g"
    cpus: str = "2"
    pids: int = 512
    tmpfs: str = "/tmp:rw,size=512m"


DEFAULT_LIMITS = DockerLimits()


class DockerSandbox:
    def __init__(self, default_image: str, limits: DockerLimits = DEFAULT_LIMITS, docker: str = "docker") -> None:
        self._image = default_image
        self._limits = limits
        self._docker = docker

    def build_argv(self, argv: list[str], cwd: Path, image: str | None, network: bool) -> list[str]:
        lim = self._limits
        # The daemon's .env may sit in the project root; mask it in the sandbox.
        secret_mounts = [
            arg for path in sorted(cwd.glob(".env*"))
            if path.is_file() and path.name != ".env.example"
            for arg in ("--mount", f"type=bind,src=/dev/null,dst=/workspace/{path.name},readonly")
        ]
        return [
            self._docker, "run", "--rm",
            "--network", "bridge" if network else "none",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "--cap-drop=ALL", "--security-opt", "no-new-privileges",
            "--read-only", "--tmpfs", lim.tmpfs,
            "--memory", lim.memory, "--cpus", lim.cpus, "--pids-limit", str(lim.pids),
            "-v", f"{cwd.resolve()}:/workspace:rw", *secret_mounts, "-w", "/workspace",
            "-e", "HOME=/tmp", *(a for k, v in GATE_ENV.items() for a in ("-e", f"{k}={v}")),
            image or self._image, *argv,
        ]

    async def exec(
        self, argv: list[str], cwd: Path, timeout_s: float, image: str | None = None, network: bool = False
    ) -> ExecResult:
        name = f"agentlab-gate-{uuid4().hex}"
        command = self.build_argv(argv, cwd, image, network)
        command[2:2] = ["--name", name]
        result = await run_argv(command, None, timeout_s, scrubbed_env())
        if result.timed_out:
            await run_argv([self._docker, "rm", "--force", name], None, 30, scrubbed_env())
        return result
