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
    argv = DockerSandbox("img").build_argv(["pytest"], tmp_path, None, network=False)
    for flag in ("--cap-drop=ALL", "--read-only", "--pids-limit"):
        assert flag in argv
    assert argv[argv.index("--network") + 1] == "none"
    assert argv[-2:] == ["img", "pytest"]


def test_secrets_never_reach_sandbox(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AGENTLAB_LLM_API_KEY", "sk-secret")
    monkeypatch.setenv("AGENTLAB_DATABASE_URL", "postgres://x")
    env = scrubbed_env()
    assert "AGENTLAB_LLM_API_KEY" not in env and "AGENTLAB_DATABASE_URL" not in env
