from __future__ import annotations

from agentlab.adapters.gates.config_gate import DEFAULT_PARSER, PARSERS
from agentlab.adapters.sandbox.docker import DockerSandbox
from agentlab.adapters.sandbox.local import scrubbed_env


def test_tsc_parser() -> None:
    d = PARSERS["tsc"]("src/a.ts(42,7): error TS2345: Argument of type 'x' is not assignable.")
    assert (d[0].file, d[0].line, d[0].col, d[0].code) == ("src/a.ts", 42, 7, "TS2345")


def test_generic_parser_ruff_mypy() -> None:
    out = DEFAULT_PARSER("src/a.py:10:5: F401 `os` imported but unused\nsrc/b.py:3: error: Incompatible types")
    assert [(x.file, x.line, x.code) for x in out] == [("src/a.py", 10, "F401"), ("src/b.py", 3, "error")]


def test_docker_argv_is_locked_down(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / ".env").write_text("API_KEY=do-not-expose")
    argv = DockerSandbox("img").build_argv(["pytest"], tmp_path, None, network=False)
    for flag in ("--cap-drop=ALL", "--read-only", "--pids-limit"):
        assert flag in argv
    assert argv[argv.index("--network") + 1] == "none"
    assert argv[-2:] == ["img", "pytest"]
    assert "type=bind,src=/dev/null,dst=/workspace/.env,readonly" in argv


def test_secrets_never_reach_sandbox(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AGENTLAB_LLM_API_KEY", "sk-secret")
    monkeypatch.setenv("AGENTLAB_DATABASE_URL", "postgres://x")
    env = scrubbed_env()
    assert "AGENTLAB_LLM_API_KEY" not in env and "AGENTLAB_DATABASE_URL" not in env


async def test_source_context_excludes_secrets_binaries_and_escapes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from agentlab.adapters.workspace import GitWorkspace

    (tmp_path / "calc.py").write_text("value = 1\n")
    (tmp_path / ".env").write_text("API_KEY=do-not-send\n")
    (tmp_path / "credentials.json").write_text('{"key":"do-not-send"}')
    (tmp_path / "image.png").write_bytes(b"\x00\xff")
    outside = tmp_path.parent / "outside-context.txt"
    outside.write_text("private content")
    (tmp_path / "link.txt").symlink_to(outside)
    ws = GitWorkspace(tmp_path)
    await ws.ensure_repo()
    assert await ws.context_files() == {"calc.py": "value = 1\n"}


async def test_docker_timeout_removes_the_container(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from agentlab.core.ports import ExecResult

    commands: list[list[str]] = []

    async def execute(argv, cwd, timeout_s, env):  # type: ignore[no-untyped-def]
        commands.append(argv)
        return ExecResult(124, "", "", 100, timed_out=len(commands) == 1)

    monkeypatch.setattr("agentlab.adapters.sandbox.docker.run_argv", execute)
    result = await DockerSandbox("image").exec(["pytest"], tmp_path, 1)
    name = commands[0][commands[0].index("--name") + 1]
    assert result.timed_out
    assert commands[1] == ["docker", "rm", "--force", name]


async def test_docker_cancellation_removes_container(monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    import asyncio

    import pytest

    from agentlab.core.ports import ExecResult

    commands = []

    async def execute(argv, cwd, timeout_s, env):  # type: ignore[no-untyped-def]
        commands.append(argv)
        if len(commands) == 1:
            raise asyncio.CancelledError
        return ExecResult(0, "", "", 0)

    monkeypatch.setattr("agentlab.adapters.sandbox.docker.run_argv", execute)
    with pytest.raises(asyncio.CancelledError):
        await DockerSandbox("image").exec(["pytest"], tmp_path, 60)
    name = commands[0][commands[0].index("--name") + 1]
    assert commands[1] == ["docker", "rm", "--force", name]


async def test_local_cancellation_kills_descendants(tmp_path):  # type: ignore[no-untyped-def]
    import asyncio
    import os
    import sys

    import pytest

    from agentlab.adapters.sandbox.local import run_argv

    script = """import subprocess,sys,pathlib,time
p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
pathlib.Path('child.pid').write_text(str(p.pid))
time.sleep(60)
"""
    task = asyncio.create_task(run_argv([sys.executable, "-c", script], tmp_path, 60, scrubbed_env()))
    async with asyncio.timeout(5):
        while not (tmp_path / "child.pid").exists():
            await asyncio.sleep(0.01)
    child_pid = int((tmp_path / "child.pid").read_text())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 6)
    # Allow the OS to reap the killed child.
    async with asyncio.timeout(5):
        while True:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            await asyncio.sleep(0.01)
