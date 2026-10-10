"""Real CPU/API smoke. Downloads models on first invocation; needs no gateway credentials."""
# ruff: noqa: RUF001
from __future__ import annotations

import json
import platform
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from agentlab.api.app import create_app
from agentlab.bootstrap import build_services
from agentlab.settings import Settings


def main() -> None:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="agentlab-local-memory-") as directory:
        scratch = Path(directory)
        svc = build_services(Settings(store_backend="memory", env_file=scratch / ".env", _env_file=None))
        with TestClient(create_app(svc)) as client:
            project = client.post("/projects", json={
                "name": "local-smoke", "goal": "validate local memory", "workspace": str(scratch),
                "runtime": "fake",
            })
            project.raise_for_status()
            assert project.json()["settings"]["retrieval"] == "hybrid"
            for index, text in enumerate([
                "项目使用 PostgreSQL 数据库保存数据。", "苹果是一种水果，常用于制作果汁。", "测试通过后才能提交代码。",
            ]):
                response = client.post("/knowledge", files={"file": (f"sample-{index}.md", text)})
                response.raise_for_status()
            cases = []
            for query, answer in [
                ("项目使用什么数据库？", "PostgreSQL"), ("哪种水果可以榨汁？", "苹果"),
                ("What database stores project data?", "PostgreSQL"),
            ]:
                response = client.post("/memory/search", json={"project_id": project.json()["id"], "query": query})
                response.raise_for_status()
                hits = response.json()
                cases.append({"query": query, "passed": bool(hits and answer in hits[0]["item"]["text"]),
                              "hits": [{"text": h["item"]["text"], "score": h["score"]} for h in hits]})
            stats = client.get("/memory/status").json()
            report = {"evaluated_date": "2026-10-10", "platform": platform.machine(),
                      "elapsed_s": round(time.monotonic() - started, 2), "stats": stats, "cases": cases,
                      "scope": (
                          "Real CPU upload/search API smoke: empty env file and default project settings, "
                          "not a retrieval benchmark."
                      ),
                      "quality_limit": (
                          "An earlier vague query (数据库如何持久化？) ranked an irrelevant code-testing note first; "
                          "broader paraphrase evaluation remains necessary."
                      )}
            Path("evals/local-memory-scorecard-real.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            )
            assert stats["embedding_backend"] == "local" and stats["embedding_ready"] and stats["rerank_ready"], stats
            assert all(c["passed"] for c in cases), cases
            print(f"Local CPU memory API smoke: {len(cases)}/{len(cases)} passed on {platform.machine()}")


if __name__ == "__main__":
    main()
