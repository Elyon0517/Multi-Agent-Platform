from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from pydantic import Field

from agentlab.core.schemas import Strict, new_id, utcnow

GLOBAL = "global"
PROJECT = "project"
RRF_K = 60
log = logging.getLogger(__name__)


def agent_ns(role: str) -> str:
    return f"agent:{role}"


def readable_namespaces(role: str) -> list[str]:
    return [GLOBAL, PROJECT, agent_ns(role)]


class MemoryKind(StrEnum):
    DOCUMENT = "document"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    NOTE = "note"


class MemoryItem(Strict):
    id: str = Field(default_factory=new_id)
    project_id: str | None
    namespace: str
    kind: MemoryKind
    text: str
    source: str = ""
    source_run_id: str | None = None
    pinned: bool = False
    embedding: list[float] | None = None
    embedding_model: str | None = None
    created_at: str = Field(default_factory=lambda: utcnow().isoformat())


class Hit(Strict):
    item: MemoryItem
    score: float


class Embedder(Protocol):
    model: str

    def available(self) -> bool: ...

    async def __call__(self, texts: list[str]) -> list[list[float]]: ...


def tokenize(text: str) -> list[str]:
    return re.findall(r"[\w\u4e00-\u9fff]+", text.lower())


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def bm25_rank(query: str, items: list[MemoryItem], k1: float = 1.5, b: float = 0.75) -> list[MemoryItem]:
    q = set(tokenize(query))
    docs = [Counter(tokenize(i.text)) for i in items]
    if not q or not docs:
        return []
    avg = sum(sum(d.values()) for d in docs) / len(docs) or 1
    df = Counter(t for d in docs for t in q if t in d)
    scored = []
    for item, d in zip(items, docs, strict=True):
        length = sum(d.values())
        s = sum(
            math.log(1 + (len(docs) - df[t] + 0.5) / (df[t] + 0.5)) * d[t] * (k1 + 1)
            / (d[t] + k1 * (1 - b + b * length / avg))
            for t in q if t in d
        )
        if s > 0:
            scored.append((s, item))
    return [i for _, i in sorted(scored, key=lambda x: -x[0])]


def rrf(rankings: list[list[MemoryItem]], k: int) -> list[Hit]:
    scores: dict[str, float] = {}
    items: dict[str, MemoryItem] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item.id] = scores.get(item.id, 0.0) + 1.0 / (RRF_K + rank + 1)
            items[item.id] = item
    return [Hit(item=items[i], score=s) for i, s in sorted(scores.items(), key=lambda x: -x[1])[:k]]


@dataclass
class InMemoryMemoryStore:
    embedder: Embedder | None = None
    last_error: str | None = None
    _items: dict[str, MemoryItem] = field(default_factory=dict)

    def _can_embed(self) -> bool:
        return self.embedder is not None and self.embedder.available()

    async def _embed(self, texts: list[str]) -> list[list[float]] | None:
        if self.embedder is None or not self._can_embed():
            return None
        try:
            return await self.embedder(texts)
        except Exception as e:  # memory must never break a run; degrade to keyword search
            log.warning("embedding failed, falling back to keyword search: %s", e)
            self.last_error = str(e)
            return None

    async def add(self, items: list[MemoryItem]) -> list[MemoryItem]:
        vectors = await self._embed([i.text for i in items]) if items else None
        if vectors is not None and self.embedder is not None:
            items = [i.model_copy(update={"embedding": v, "embedding_model": self.embedder.model})
                     for i, v in zip(items, vectors, strict=True)]
        for i in items:
            self._items[i.id] = i
        return items

    def items_in(self, namespace: str, project_id: str | None = None) -> list[MemoryItem]:
        return [i for i in self._items.values()
                if i.namespace == namespace and (namespace == GLOBAL or i.project_id == project_id)]

    def stats(self) -> dict[str, object]:
        items = list(self._items.values())
        return {"items": len(items), "embedded": sum(1 for i in items if i.embedding),
                "embedding_model": self.embedder.model if self.embedder else None,
                "embedding_ready": self._can_embed(), "last_error": self.last_error}

    def delete_source(self, namespace: str, source: str) -> int:
        doomed = [k for k, i in self._items.items() if i.namespace == namespace and i.source == source]
        for k in doomed:
            del self._items[k]
        return len(doomed)

    def _scope(self, project_id: str | None, namespaces: list[str]) -> list[MemoryItem]:
        return [i for i in self._items.values() if i.namespace in namespaces
                and (i.namespace == GLOBAL or i.project_id == project_id)]

    async def search(self, project_id: str | None, namespaces: list[str], query: str, k: int = 8) -> list[Hit]:
        pool = self._scope(project_id, namespaces)
        rankings = [bm25_rank(query, pool)[:50]]
        vec = [i for i in pool if i.embedding]
        qvs = await self._embed([query]) if vec else None
        if qvs:
            rankings.append(sorted(vec, key=lambda i: -cosine(qvs[0], i.embedding or []))[:50])
        pinned = [i for i in pool if i.pinned]
        return rrf([*rankings, pinned], k)
