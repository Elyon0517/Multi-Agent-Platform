import subprocess
from pathlib import Path

import pytest

from agentlab.adapters.workspace import GitWorkspace
from agentlab.core.config import load_config
from agentlab.core.llm.tools import WorkerTools

CONFIG = load_config(Path(__file__).resolve().parents[2] / "config")
READ = {"workspace_excerpt", "workspace_read_next", "workspace_read_status", "workspace_read", "workspace_search", "memory_search", "git_status", "git_branch", "git_log", "git_diff", "git_show"}


async def _memory(query: str) -> dict:
    return {}


@pytest.fixture
async def workspace(tmp_path: Path):
    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    (tmp_path / "app.ts").write_text("export const add = (a: number, b: number) => a - b;\n")
    git("init", "-q")
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    git("branch", "feature")
    ws = GitWorkspace(tmp_path)
    yield ws
    ws.close()


@pytest.mark.parametrize("role", ["correctness-reviewer", "arch-reviewer", "test-style-reviewer", "planner"])
async def test_reviewers_and_planner_read_broadly_but_never_write(workspace, role: str) -> None:
    tools = WorkerTools(role, CONFIG.agents[role].tool_grants, workspace, None, _memory)
    names = {spec["function"]["name"] for spec in tools.specs}
    assert names == READ
    assert "export const add" in (await tools.execute("git_show", {"ref": "feature", "path": "app.ts"}))["text"]
    assert (await tools.execute("workspace_search", {"query": "a - b"}))[0]["path"] == "app.ts"
    with pytest.raises(ValueError):
        await tools.execute("workspace_write", {"path": "app.ts", "content": "x"})


async def test_coder_writes_and_reads(workspace) -> None:
    tools = WorkerTools("coder", CONFIG.agents["coder"].tool_grants, workspace, None, _memory)
    names = {spec["function"]["name"] for spec in tools.specs}
    assert READ | {"workspace_write"} <= names  # gate_run appears only when the project has checks
    await tools.execute("workspace_write", {"path": "app.ts", "content": "export const add = (a: number, b: number) => a + b;\n"})
    assert "a + b" in (await tools.execute("workspace_read", {"path": "app.ts"}))["text"]
