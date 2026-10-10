import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentlab.api.app import create_app
from tests.unit.test_memory_project import _svc


class _Proc:
    def __init__(self, code: int, out: bytes, err: bytes) -> None:
        self.returncode, self._result = code, (out, err)

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._result


@pytest.mark.parametrize(
    ("code", "out", "err", "status", "path"),
    [
        (0, b"/Users/me/my repo/\n", b"", 200, "/Users/me/my repo"),
        (1, b"", b"execution error: User canceled. (-128)", 200, None),
        (1, b"", b"some other failure", 500, None),
    ],
)
def test_pick_folder_returns_chosen_path_or_cancel(tmp_path: Path, monkeypatch, code, out, err, status, path):
    calls: list[tuple[str, ...]] = []

    async def fake_exec(*args: str, **_: object) -> _Proc:
        calls.append(args)
        return _Proc(code, out, err)

    monkeypatch.setattr("agentlab.api.app.sys.platform", "darwin")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    with TestClient(create_app(_svc(tmp_path))) as client:
        response = client.post("/local/pick-folder", json={})
    assert response.status_code == status
    if status == 200:
        assert response.json() == {"path": path}
    assert calls and calls[0][0] == "osascript"


def test_pick_folder_requires_json_and_macos(tmp_path: Path, monkeypatch):
    with TestClient(create_app(_svc(tmp_path))) as client:
        # A cross-site "simple" POST cannot carry a JSON body, so it never reaches the dialog.
        monkeypatch.setattr("agentlab.api.app.sys.platform", "darwin")
        assert client.post("/local/pick-folder", content=b"{}", headers={"content-type": "text/plain"}).status_code == 422
        monkeypatch.setattr("agentlab.api.app.sys.platform", "linux")
        assert client.post("/local/pick-folder", json={}).status_code == 501
