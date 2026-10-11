from pathlib import Path

import pytest

from agentlab.adapters.workspace import GitWorkspace, SourceUnavailable, WorkspaceEscape
from agentlab.core.llm.tools import WorkerTools
from agentlab.core.schemas import FileEdit


async def _search(query: str) -> dict:
    return {}


async def test_reading_a_directory_or_large_file_is_an_ordinary_tool_error(tmp_path: Path) -> None:
    (tmp_path / "src" / "panel").mkdir(parents=True)
    (tmp_path / "src" / "panel" / "index.tsx").write_text("export {}\n")
    (tmp_path / "big.txt").write_text("x" * 200_000)
    (tmp_path / "blob.bin").write_bytes(b"\xff\xfe\x00\x01")
    ws = GitWorkspace(tmp_path)
    await ws.ensure_repo()
    tools = WorkerTools("coder", ["workspace_read"], ws, None, _search)
    for path, kind in [("src/panel", "is_directory"), ("big.txt", "file_too_large"), ("blob.bin", "binary_file")]:
        with pytest.raises(SourceUnavailable) as caught:
            await tools.execute("workspace_read", {"path": path})
        assert caught.value.kind.startswith(kind)
        assert not isinstance(caught.value, PermissionError)  # a PermissionError would pause the whole run
    assert (await tools.execute("workspace_read", {"path": "src/panel/index.tsx"}))["text"] == "export {}\n"
    with pytest.raises(WorkspaceEscape):  # real boundary violations still stop the run
        await tools.execute("workspace_read", {"path": "../outside.txt"})
    ws.close()


async def test_long_source_can_be_read_through_the_worker_tool_without_losing_the_tail(tmp_path: Path) -> None:
    content = "".join(f"const value{i} = '{'x' * 30}';\n" for i in range(900))
    (tmp_path / "panel.tsx").write_text(content)
    ws = GitWorkspace(tmp_path)
    tools = WorkerTools("coder", ["workspace_read"], ws, None, _search)
    first = await tools.execute("workspace_read", {"path": "panel.tsx"})
    assert "continue with line_start=201" in first["text"]
    tail = await tools.execute("workspace_read", {"path": "panel.tsx", "line_start": 801, "line_end": 900})
    assert tail["text"] == "".join(content.splitlines(keepends=True)[800:])
    assert "value899" in tail["text"]
    for args in ({"line_start": 0}, {"line_start": True}, {"line_start": 10, "line_end": 2}):
        with pytest.raises(ValueError):
            await tools.execute("workspace_read", {"path": "panel.tsx", **args})
    with pytest.raises(WorkspaceEscape):
        await tools.execute("workspace_read", {"path": "../outside.tsx", "line_start": 1})
    ws.close()


async def test_dependency_reads_do_not_pause_but_writes_and_external_symlinks_remain_blocked(tmp_path: Path) -> None:
    ws = GitWorkspace(tmp_path)
    dependency = tmp_path / "node_modules" / "package"
    dependency.mkdir(parents=True)
    (dependency / "index.js").write_text("export {};\n")
    with pytest.raises(SourceUnavailable, match="excluded_dependency_directory"):
        ws.read_source("node_modules/package/index.js")
    with pytest.raises(WorkspaceEscape):
        ws.apply_edits([FileEdit(path="node_modules/package/index.js", content="changed")])
    external = tmp_path.parent / f"{tmp_path.name}-external"
    external.mkdir()
    (dependency / "external").symlink_to(external, target_is_directory=True)
    with pytest.raises(WorkspaceEscape):
        ws.read_source("node_modules/package/external/index.js")
    with pytest.raises(WorkspaceEscape):
        ws.read_source(".env")
    ws.close()
