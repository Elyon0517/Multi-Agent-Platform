from pathlib import Path

import pytest

from agentlab.adapters.workspace import GitWorkspace, SourceUnavailable, WorkspaceEscape
from agentlab.core.llm.tools import WorkerTools
from agentlab.core.schemas import FileEdit


async def _search(query: str) -> dict:
    return {}


async def test_reading_a_directory_or_binary_file_is_an_ordinary_tool_error(tmp_path: Path) -> None:
    (tmp_path / "src" / "panel").mkdir(parents=True)
    (tmp_path / "src" / "panel" / "index.tsx").write_text("export {}\n")
    (tmp_path / "big.txt").write_text("x" * 200_000)
    (tmp_path / "blob.bin").write_bytes(b"\xff\xfe\x00\x01")
    ws = GitWorkspace(tmp_path)
    await ws.ensure_repo()
    tools = WorkerTools("coder", ["workspace_read"], ws, None, _search)
    for path, kind in [("src/panel", "is_directory"), ("blob.bin", "binary_file")]:
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


async def test_large_unicode_single_line_paging_is_lossless(tmp_path: Path) -> None:
    import re
    content = ('评分🙂"\\\t' * 12000) + "tail\nlast line"
    (tmp_path / "large.txt").write_text(content)
    ws = GitWorkspace(tmp_path)
    tools = WorkerTools("coder", ["workspace_read"], ws, None, _search)
    args = {"path": "large.txt"}
    pieces = []
    for _ in range(100):
        page = (await tools.execute("workspace_read", args))["text"]
        if "\n[more " not in page:
            pieces.append(page)
            break
        body, marker = page.rsplit("\n[more ", 1)
        assert len(body.encode()) <= 12000
        pieces.append(body)
        args = {"path": "large.txt", "line_start": int(re.search(r"line_start=(\d+)", marker)[1])}
        offset = re.search(r"char_start=(\d+)", marker)
        if offset:
            args["char_start"] = int(offset[1])
    else:
        raise AssertionError("pagination did not finish")
    assert "".join(pieces) == content
    ws.close()


async def test_search_and_listing_include_large_file_tail(tmp_path: Path) -> None:
    (tmp_path / "large.txt").write_text("padding\n" * 20000 + "unique needle\n")
    ws = GitWorkspace(tmp_path)
    tools = WorkerTools("coder", ["workspace_read", "workspace_search"], ws, None, _search)
    assert "large.txt" in await tools.execute("workspace_read", {"path": ""})
    assert await tools.execute("workspace_search", {"query": "unique needle"}) == [
        {"path": "large.txt", "line": 20001, "text": "unique needle"}
    ]
    (tmp_path / "large.txt").write_text("padding\n" * 20000 + "sk-" + "a" * 30)
    with pytest.raises(WorkspaceEscape):
        await tools.execute("workspace_read", {"path": "large.txt", "line_end": 1})
    assert await tools.execute("workspace_search", {"query": "padding"}) == []
    ws.close()


async def test_search_long_line_returns_readable_match_offset(tmp_path: Path) -> None:
    (tmp_path / "long.html").write_text("x" * 150000 + "Target evidence" + "y" * 1000)
    ws = GitWorkspace(tmp_path)
    tools = WorkerTools("coder", ["workspace_read", "workspace_search"], ws, None, _search)
    matches = await tools.execute("workspace_search", {"query": "Target evidence"})
    assert matches[0]["char_start"] == 149900
    assert "Target evidence" in matches[0]["text"]
    page = await tools.execute("workspace_read", {
        "path": "long.html", "line_start": matches[0]["line"], "char_start": matches[0]["char_start"],
    })
    assert "Target evidence" in page["text"]
    ws.close()


async def test_jump_is_deferred_and_cursors_survive_tool_recreation(tmp_path: Path) -> None:
    import json
    content = ''.join(f'{i}: {chr(34) * 100}\n' for i in range(300))
    (tmp_path / 'evidence.txt').write_text(content)
    ws = GitWorkspace(tmp_path)
    state = {}
    tools = WorkerTools('coder', ['workspace_read'], ws, None, _search, state)
    first = await tools.execute('workspace_read', {'path': 'evidence.txt', 'line_start': 1, 'line_end': 200})
    assert first['pending_count'] == 1
    saved = dict(state['pending'][0])
    tools = WorkerTools('coder', ['workspace_read'], ws, None, _search, json.loads(json.dumps(state)))
    jump = await tools.execute('workspace_read', {'path': 'evidence.txt', 'line_start': 201, 'line_end': 300})
    assert jump['actual_range'] == saved
    assert jump['request_deferred']
    pages = [first['text'], jump['text']]
    for _ in range(30):
        if not (await tools.execute('workspace_read_status', {}))['pending']:
            break
        page = await tools.execute('workspace_read_next', {})
        assert len(json.dumps(page, ensure_ascii=False).encode()) < 16384
        pages.append(page['text'])
    else:
        raise AssertionError('cursor failed to drain')
    delivered = ''.join(page.split('\n[more ')[0] for page in pages)
    assert delivered == content
    ws.close()


async def test_targeted_excerpt_does_not_queue_whole_html(tmp_path: Path) -> None:
    text = '<html>' + 'x' * 100000 + 'evidence clause' + 'y' * 200000 + '</html>'
    (tmp_path / 'raw.html').write_text(text)
    ws = GitWorkspace(tmp_path)
    tools = WorkerTools('coder', ['workspace_read'], ws, None, _search)
    args = {'path': 'raw.html', 'line_start': 1, 'char_start': 100006, 'char_count': 15}
    result = await tools.execute('workspace_excerpt', args)
    assert result['text'] == 'evidence clause'
    assert (await tools.execute('workspace_read_status', {}))['pending'] == []
    with pytest.raises(WorkspaceEscape):
        await tools.execute('workspace_excerpt', {**args, 'path': '../outside'})
    with pytest.raises(ValueError):
        await tools.execute('workspace_excerpt', {**args, 'char_count': 2001})
    ws.close()
