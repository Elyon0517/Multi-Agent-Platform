from __future__ import annotations

import time
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from agentlab.api.app import create_app
from agentlab.bootstrap import Services, build_services
from agentlab.core.memory.documents import UnsupportedDocument, chunk, extract_text
from agentlab.core.memory.store import GLOBAL, PROJECT, InMemoryMemoryStore, MemoryItem, MemoryKind, agent_ns
from agentlab.secrets import EnvFile, mask
from agentlab.settings import Settings
from tests.conftest import CONFIG_DIR

RESUME = "Elyon has 8 years of Python and TypeScript experience, led payments platform migration at Walmart."


def _pdf(text: str) -> bytes:
    w = PdfWriter()
    page = w.add_blank_page(612, 792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject(
        {NameObject("/F1"): w._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 10 Tf 40 700 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = w._add_object(stream)
    buf = BytesIO()
    w.write(buf)
    return buf.getvalue()


def _svc(tmp: Path) -> Services:
    (tmp / ".env").write_text("UNRELATED=1\n")
    return build_services(Settings(store_backend="memory", config_dir=CONFIG_DIR, data_dir=tmp, env_file=tmp / ".env", runtime="fake",
                                   llm_base_url=None, llm_api_key=None, _env_file=None))  # type: ignore[call-arg]


def test_mask_never_reveals_more_than_last_four() -> None:
    assert mask("sk-abcdefghijkl1234").endswith("1234") and "abcd" not in mask("sk-abcdefghijkl1234")
    assert mask("short") == "\u2022" * 8 and mask("") == ""


def test_env_file_update_preserves_other_lines_and_rejects_unknown(tmp_path: Path) -> None:
    env = EnvFile(tmp_path / ".env")
    env.path.write_text("# comment\nOTHER=x\nAGENTLAB_LLM_API_KEY=old\n")
    env.update({"AGENTLAB_LLM_API_KEY": "sk-new-secret-9999", "AGENTLAB_LLM_BASE_URL": "https://gw"})
    text = env.path.read_text()
    assert "# comment" in text and "OTHER=x" in text and "sk-new-secret-9999" in text
    assert oct(env.path.stat().st_mode)[-3:] == "600"
    with pytest.raises(KeyError):
        env.update({"PATH": "/evil"})
    with pytest.raises(ValueError):
        env.update({"AGENTLAB_LLM_BASE_URL": "a\nAGENTLAB_X=1"})


def test_pdf_and_markdown_extraction_and_chunking() -> None:
    assert "8 years" in extract_text("cv.pdf", _pdf(RESUME))
    assert extract_text("notes.md", b"# hi") == "# hi"
    with pytest.raises(UnsupportedDocument):
        extract_text("cv.docx", b"x")
    chunks = list(chunk("para one.\n\n" + "x" * 3000, size=1000, overlap=100))
    assert all(len(c) <= 1000 for c in chunks) and len(chunks) >= 3


async def test_three_memory_layers_are_scoped() -> None:
    m = InMemoryMemoryStore()
    await m.add([
        MemoryItem(project_id=None, namespace=GLOBAL, kind=MemoryKind.DOCUMENT, text=RESUME, source="cv.pdf"),
        MemoryItem(project_id="p1", namespace=PROJECT, kind=MemoryKind.NOTE, text="p1 uses Python FastAPI"),
        MemoryItem(project_id="p2", namespace=PROJECT, kind=MemoryKind.NOTE, text="p2 uses Python Django"),
        MemoryItem(project_id="p1", namespace=agent_ns("coder"), kind=MemoryKind.NOTE, text="coder Python tip"),
    ])
    reviewer = {h.item.text for h in await m.search("p1", [GLOBAL, PROJECT, agent_ns("arch-reviewer")], "Python")}
    assert RESUME in reviewer and "p1 uses Python FastAPI" in reviewer
    assert "p2 uses Python Django" not in reviewer and "coder Python tip" not in reviewer
    coder = {h.item.text for h in await m.search("p1", [GLOBAL, PROJECT, agent_ns("coder")], "Python")}
    assert "coder Python tip" in coder


class FakeEmbedder:
    model = "fake-embed"

    def available(self) -> bool:
        return True

    async def __call__(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] if "resume" in t.lower() or "career" in t.lower() else [0.0, 1.0] for t in texts]


class BrokenEmbedder(FakeEmbedder):
    async def __call__(self, texts: list[str]) -> list[list[float]]:
        raise ConnectionError("gateway down")


async def test_embedding_outage_degrades_to_keyword_search() -> None:
    m = InMemoryMemoryStore(BrokenEmbedder())
    await m.add([MemoryItem(project_id=None, namespace=GLOBAL, kind=MemoryKind.DOCUMENT, text=RESUME)])
    hits = await m.search(None, [GLOBAL], "Python")
    assert hits and hits[0].item.embedding is None and m.stats()["last_error"] == "ConnectionError"


async def test_run_survives_broken_memory(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    svc.knowledge.memory.embedder = BrokenEmbedder()
    driver = svc.driver(seed_ws(tmp_path), "fake", "python")
    await driver.workspace.ensure_repo()  # type: ignore[attr-defined]
    run = await driver.run(driver.create("fix add").id)
    assert run.status == "WAITING_HUMAN"


async def test_vector_ranking_finds_semantic_match_without_keyword_overlap() -> None:
    m = InMemoryMemoryStore(FakeEmbedder())
    await m.add([MemoryItem(project_id=None, namespace=GLOBAL, kind=MemoryKind.DOCUMENT, text="My resume summary"),
                 MemoryItem(project_id=None, namespace=GLOBAL, kind=MemoryKind.DOCUMENT, text="Unrelated")])
    hits = await m.search(None, [GLOBAL], "career", k=1)
    assert hits[0].item.text == "My resume summary" and m.stats()["embedded"] == 2


def test_settings_api_masks_key_and_runtime_picks_it_up(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    with TestClient(create_app(svc)) as c:
        assert not any(v["is_set"] for v in c.get("/settings").json())
        res = c.put("/settings", json={"values": {"AGENTLAB_LLM_API_KEY": "sk-live-abcdef-7777",
                                                  "AGENTLAB_LLM_BASE_URL": "https://gw.local/v1"}})
        body = res.text
        assert "sk-live-abcdef" not in body and "7777" in body and "https://gw.local/v1" in body
        assert c.put("/settings", json={"values": {"HOME": "/x"}}).status_code == 422
    assert svc.gateway() == ("https://gw.local/v1", "sk-live-abcdef-7777")
    assert "UNRELATED=1" in (tmp_path / ".env").read_text()


def test_global_upload_project_plan_and_run_feed_memory_and_progress(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    with TestClient(create_app(svc)) as c:
        up = c.post("/knowledge", files={"file": ("cv.pdf", _pdf(RESUME), "application/pdf")}).json()
        assert up["source"] == "cv.pdf" and up["chunks"] >= 1
        assert c.post("/knowledge", files={"file": ("x.docx", b"x", "application/octet-stream")}).status_code == 422

        from agentlab.demo import seed_demo_workspace

        workspace = seed_demo_workspace(tmp_path / "workspace")
        project = c.post("/projects", json={"name": "calc", "goal": "Python calc library",
                                            "workspace": str(workspace), "runtime": "fake"}).json()
        assert [p["title"] for p in project["phases"]] == ["Foundation", "Polish"]
        step = project["phases"][0]["steps"][0]

        run = c.post("/runs", json={"goal": "Python calc add", "runtime": "fake", "language": "python",
                                    "project_id": project["id"], "step_id": step["id"]}).json()
        # Branch mode: the run edits the project repository directly.
        assert Path(run["workspace"]) == workspace.resolve()
        assert c.get(f"/projects/{project['id']}").json()["phases"][0]["steps"][0]["status"] == "doing"
        for _ in range(100):
            if c.get(f"/runs/{run['id']}").json()["run"]["status"] == "DONE":
                break
            time.sleep(0.1)
        assert c.get(f"/runs/{run['id']}").json()["pending_approval"] is None
        for _ in range(50):
            p = c.get(f"/projects/{project['id']}").json()
            if p["phases"][0]["steps"][0]["status"] == "done":
                break
            time.sleep(0.1)
        assert p["phases"][0]["steps"][0]["run_ids"] == [run["id"]]

        project_mem = c.get("/memory", params={"scope": "project", "project_id": project["id"]}).json()
        assert not any("approved" in m["text"] for m in project_mem)
        agent_mem = c.get("/memory", params={"scope": "agent", "role": "arch-reviewer",
                                             "project_id": project["id"]}).json()
        assert agent_mem, "reviewer that flagged a blocking issue should remember it"


async def test_driver_injects_global_project_and_own_memory_into_agent_context(tmp_path: Path) -> None:
    from agentlab.adapters.runtime.fake import FakeRuntime

    svc = _svc(tmp_path)
    await svc.knowledge.ingest("cv.md", RESUME.encode())
    project = svc.projects.create("calc", "calc", str(tmp_path))
    await svc.knowledge.note(project.id, agent_ns("coder"), "coder: Python prefer pure functions")
    await svc.knowledge.note(project.id, agent_ns("planner"), "planner-only Python secret")
    driver = svc.driver(seed_ws(tmp_path), "fake", "python")
    await driver.workspace.ensure_repo()  # type: ignore[attr-defined]
    run = driver.create("Python calc add", project_id=project.id)
    await driver.run(run.id)
    assert isinstance(driver.runtime, FakeRuntime)
    coder_ctx = next(i.context for r, i in driver.runtime.inputs if r == "coder")
    texts = [m["text"] for m in coder_ctx["memory"]]
    assert any("8 years" in t for t in texts) and any("pure functions" in t for t in texts)
    assert not any("planner-only" in t for t in texts)
    assert coder_ctx["project"]["name"] == "calc"


def seed_ws(tmp: Path) -> Path:
    from agentlab.demo import seed_demo_workspace
    return seed_demo_workspace(tmp / "ws")


async def test_vectors_from_a_different_embedding_version_are_not_mixed() -> None:
    embedder = FakeEmbedder()
    embedder.version = 1
    memory = InMemoryMemoryStore(embedder)
    await memory.add([MemoryItem(project_id=None, namespace=GLOBAL, kind=MemoryKind.DOCUMENT, text="resume")])
    assert (await memory.search(None, [GLOBAL], "career"))[0].item.embedding_version == 1
    embedder.version = 2
    assert await memory.search(None, [GLOBAL], "career") == []


async def test_bad_embedding_dimensions_degrade_without_marking_ready() -> None:
    embedder = FakeEmbedder()
    embedder.dimensions = 3
    memory = InMemoryMemoryStore(embedder)
    await memory.add([MemoryItem(project_id=None, namespace=GLOBAL, kind=MemoryKind.DOCUMENT, text="resume")])
    assert not memory.stats()["embedding_ready"]
    assert memory.stats()["last_error"] == "ValueError"
    assert await memory.search(None, [GLOBAL], "resume")
