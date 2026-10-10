"""Lazy CPU models. Loading, downloading and inference never run on the event loop."""
from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any

from agentlab.adapters.runtime.raw import OpenAICompatEmbedder
from agentlab.core.memory.documents import chunk


class LocalEmbedder:
    backend = "local"

    def __init__(self, model: str, dimensions: int, version: int, cache_dir: Path) -> None:
        self.model, self.dimensions, self.version = model, dimensions, version
        self.cache_dir = cache_dir
        self._engine: Any = None
        self._lock = threading.Lock()
        self._retry_at = 0.0

    def available(self) -> bool:
        return True

    def _encode(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            if time.monotonic() < self._retry_at:
                raise RuntimeError("local embedding temporarily unavailable")
            try:
                if self._engine is None:
                    from fastembed import TextEmbedding

                    self._engine = TextEmbedding(self.model, cache_dir=str(self.cache_dir), threads=2,
                                                 providers=["CPUExecutionProvider"])
                # Existing document chunks can exceed the model token window in Chinese.
                parts = [list(chunk(text, size=400, overlap=50)) or [text] for text in texts]
                rows = iter(self._engine.embed([part for doc in parts for part in doc], batch_size=16))
                result: list[list[float]] = []
                for doc in parts:
                    vectors = [next(rows).tolist() for _ in doc]
                    result.append([sum(float(x) for x in column) / len(doc)
                                   for column in zip(*vectors, strict=True)])
                return result
            except Exception:
                self._retry_at = time.monotonic() + 60
                raise

    async def __call__(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._encode, texts)


class RoutedEmbedder:
    """An explicit URL overrides local inference; an absent key is valid for Ollama."""
    def __init__(self, remote: OpenAICompatEmbedder, local: LocalEmbedder) -> None:
        self.remote, self.local = remote, local
        self._failed_creds: tuple[str | None, str | None] | None = None
        self._retry_at = 0.0

    @property
    def backend(self) -> str:
        return "remote" if self.selected is self.remote else "local"

    @property
    def selected(self) -> OpenAICompatEmbedder | LocalEmbedder:
        cooling_down = self._failed_creds == self.remote._creds() and time.monotonic() < self._retry_at
        return self.remote if self.remote.available() and not cooling_down else self.local

    @property
    def model(self) -> str:
        return self.selected.model

    @property
    def dimensions(self) -> int | None:
        return self.selected.dimensions

    @property
    def version(self) -> int:
        return self.selected.version

    def available(self) -> bool:
        return self.selected.available()

    async def __call__(self, texts: list[str]) -> list[list[float]]:
        selected = self.selected
        try:
            return await selected(texts)
        except Exception:
            if selected is self.remote:
                self._failed_creds = self.remote._creds()
                self._retry_at = time.monotonic() + 60
            raise


class LocalReranker:
    def __init__(self, model: str, cache_dir: Path) -> None:
        self.model, self.cache_dir = model, cache_dir
        self._engine: Any = None
        self._lock = threading.Lock()
        self._retry_at = 0.0

    def _score(self, query: str, documents: list[str]) -> list[float]:
        with self._lock:
            if time.monotonic() < self._retry_at:
                raise RuntimeError("local reranker temporarily unavailable")
            try:
                if self._engine is None:
                    from fastembed.rerank.cross_encoder import TextCrossEncoder

                    self._engine = TextCrossEncoder(self.model, cache_dir=str(self.cache_dir), threads=2,
                                                     providers=["CPUExecutionProvider"])
                parts = [list(chunk(text, size=400, overlap=50)) or [text] for text in documents]
                scores = iter(self._engine.rerank(query, [part for doc in parts for part in doc], batch_size=8))
                return [max(float(next(scores)) for _ in doc) for doc in parts]
            except Exception:
                self._retry_at = time.monotonic() + 60
                raise

    async def __call__(self, query: str, documents: list[str]) -> list[float]:
        return await asyncio.to_thread(self._score, query, documents)
