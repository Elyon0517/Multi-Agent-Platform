from pathlib import Path

import pytest

from agentlab.adapters.workspace import GitWorkspace, SourceUnavailable, WorkspaceEscape
from agentlab.core.llm.tools import WorkerTools


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
