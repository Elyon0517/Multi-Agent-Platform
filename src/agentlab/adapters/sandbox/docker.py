from __future__ import annotations

import asyncio
import csv
import io
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


def _credential_name(name: str) -> bool:
    name = name.casefold()
    return ((name.startswith(".env") and name != ".env.example")
            or name in {".git", ".ssh", ".aws", ".azure", ".gnupg", "credentials.json",
                        "secrets.json", "id_rsa", "id_ed25519"}
            or Path(name).suffix in {".pem", ".key"})


def _bind_mask(rel: str) -> str:
    # Docker's --mount uses CSV; a valid workspace filename may contain commas.
    output = io.StringIO()
    csv.writer(output, lineterminator="").writerow([
        "type=bind", "src=/dev/null", "dst=/workspace/" + rel, "readonly",
    ])
    return output.getvalue()


def credential_masks(cwd: Path) -> list[str]:
    """Hide credentials at any depth, including nested repos and internal symlink aliases."""
    root = cwd.resolve()
    pending, visited = [root], set()
    files: set[str] = set()
    directories: set[str] = set()
    while pending:
        directory = pending.pop()
        if directory in visited:
            continue
        visited.add(directory)
        for entry in directory.iterdir():
            resolved = entry.resolve()
            sensitive = _credential_name(entry.name)
            if not resolved.is_relative_to(root):
                if sensitive:
                    raise ValueError("credential symlink escapes workspace")
                # External symlink targets are not part of the workspace bind mount.
                continue
            if resolved == root:
                if sensitive:
                    raise ValueError("credential symlink aliases the workspace root")
                continue
            rel = resolved.relative_to(root).as_posix()
            if entry.is_dir():
                if sensitive:
                    directories.add(rel)
                else:
                    pending.append(resolved)
            elif sensitive or _credential_name(resolved.name):
                if not entry.is_file():
                    raise ValueError("credential entry is not a regular file")
                files.add(rel)
    # Never mount a child beneath an already-masked directory.
    def covered(rel: str) -> bool:
        return any(rel.startswith(d + "/") for d in directories)
    args: list[str] = []
    for rel in sorted(directories):
        if not covered(rel):
            args.extend(["--tmpfs", f"/workspace/{rel}:ro,size=1m"])
    for rel in sorted(files):
        if not covered(rel):
            args.extend(["--mount", _bind_mask(rel)])
    return args


class DockerSandbox:
    def __init__(self, default_image: str, limits: DockerLimits = DEFAULT_LIMITS, docker: str = "docker") -> None:
        self._image = default_image
        self._limits = limits
        self._docker = docker

    def build_argv(self, argv: list[str], cwd: Path, image: str | None, network: bool) -> list[str]:
        lim = self._limits
        secret_mounts = credential_masks(cwd)
        return [
            self._docker,
            "run",
            "--rm",
            "--network",
            "bridge" if network else "none",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--cap-drop=ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            lim.tmpfs,
            "--memory",
            lim.memory,
            "--cpus",
            lim.cpus,
            "--pids-limit",
            str(lim.pids),
            "-v",
            f"{cwd.resolve()}:/workspace:rw",
            *secret_mounts,
            "-w",
            "/workspace",
            "-e",
            "HOME=/tmp",
            *(a for k, v in GATE_ENV.items() for a in ("-e", f"{k}={v}")),
            image or self._image,
            *argv,
        ]

    async def exec(
        self, argv: list[str], cwd: Path, timeout_s: float, image: str | None = None, network: bool = False
    ) -> ExecResult:
        name = f"agentlab-gate-{uuid4().hex}"
        command = self.build_argv(argv, cwd, image, network)
        command[2:2] = ["--name", name]
        try:
            result = await run_argv(command, None, timeout_s, scrubbed_env())
        except asyncio.CancelledError:
            await run_argv([self._docker, "rm", "--force", name], None, 30, scrubbed_env())
            raise
        if result.timed_out:
            await run_argv([self._docker, "rm", "--force", name], None, 30, scrubbed_env())
        return result
