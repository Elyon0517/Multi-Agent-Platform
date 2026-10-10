from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentlab.adapters.runtime.local_memory import LocalEmbedder, LocalReranker, RoutedEmbedder
from agentlab.adapters.runtime.raw import OpenAICompatEmbedder
from agentlab.core.memory.store import GLOBAL, InMemoryMemoryStore, MemoryItem, MemoryKind


def item(text: str, pinned: bool = False) -> MemoryItem:
    return MemoryItem(project_id=None, namespace=GLOBAL, kind=MemoryKind.DOCUMENT, text=text, pinned=pinned)


async def test_local_loading_and_inference_run_off_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    main_thread = threading.get_ident()
    calls = []

    class Engine:
        def __init__(self, *args: object, **kwargs: object) -> None:
            assert threading.get_ident() != main_thread
            assert kwargs['providers'] == ['CPUExecutionProvider']
            calls.append('load')

        def embed(self, texts: list[str], **kwargs: object):
            assert threading.get_ident() != main_thread
            return [SimpleNamespace(tolist=lambda: [1.0, 0.0]) for _ in texts]

    monkeypatch.setattr('fastembed.TextEmbedding', Engine)
    encoder = LocalEmbedder('test', 2, 1, tmp_path)
    await asyncio.gather(encoder(['中文']), encoder(['another']))
    assert calls == ['load']


def test_url_selects_remote_without_key_and_clearing_restores_local(tmp_path: Path) -> None:
    creds: list[str | None] = [None, None]
    remote = OpenAICompatEmbedder(lambda: (creds[0], creds[1]), 'remote', 3072)
    routed = RoutedEmbedder(remote, LocalEmbedder('local', 384, 1, tmp_path))
    assert routed.backend == 'local' and routed.model == 'local' and routed.dimensions == 384
    creds[0] = 'http://localhost:11434/v1'
    assert routed.backend == 'remote' and routed.model == 'remote' and routed.available()
    creds[0] = None
    assert routed.backend == 'local'


async def test_remote_uses_dummy_key_only_when_key_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []

    class Client:
        def __init__(self, **kwargs: object) -> None:
            seen.append(kwargs)
            self.embeddings = self

        async def create(self, **kwargs: object):
            return SimpleNamespace(data=[SimpleNamespace(embedding=[1.0])])

        async def close(self) -> None:
            pass

    monkeypatch.setattr('openai.AsyncOpenAI', Client)
    encoder = OpenAICompatEmbedder(lambda: ('http://localhost:11434/v1', None), 'ollama')
    assert await encoder(['test']) == [[1.0]]
    assert seen[0]['api_key'] == 'ollama'


async def test_rerank_orders_candidates_keeps_pinned_and_degrades(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Engine:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def rerank(self, query: str, documents: list[str], **kwargs: object):
            return [10.0 if 'best' in d else -1.0 for d in documents]

    monkeypatch.setattr('fastembed.rerank.cross_encoder.TextCrossEncoder', Engine)
    m = InMemoryMemoryStore()
    m.reranker = LocalReranker('test', tmp_path)
    await m.add([item('test first'), item('test best'), item('test pinned', True)], embed=False)
    hits = await m.search(None, [GLOBAL], 'test', k=2)
    assert [h.item.text for h in hits] == ['test pinned', 'test best']
    assert m.rerank_ready

    class Broken:
        model = 'broken'

        async def __call__(self, query: str, documents: list[str]) -> list[float]:
            raise ConnectionError('offline')

    m.reranker = Broken()
    assert await m.search(None, [GLOBAL], 'test')
    assert not m.rerank_ready and m.rerank_error == 'ConnectionError'
    m.rerank_error = None
    await m.search(None, [GLOBAL], 'test', use_vectors=False)
    assert m.rerank_error is None


async def test_model_switch_reports_stale_vectors_and_reindex_replaces_them(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Engine:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def embed(self, texts: list[str], **kwargs: object):
            return [SimpleNamespace(tolist=lambda: [0.5, 0.5]) for _ in texts]

    monkeypatch.setattr('fastembed.TextEmbedding', Engine)
    m = InMemoryMemoryStore(LocalEmbedder('new', 2, 1, tmp_path))
    old = item('test old').model_copy(update={'embedding': [1.0] * 3, 'embedding_model': 'old', 'embedding_version': 1})
    await m.add([old], embed=False)
    assert m.stats()['compatible_embedded'] == 0
    refreshed = await m.add(m.items_in(GLOBAL))
    assert refreshed[0].id == old.id and refreshed[0].embedding_dimensions == 2
    assert m.stats()['compatible_embedded'] == 1


async def test_download_failure_does_not_repeat_or_break_keyword_search(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def broken(*args: object, **kwargs: object):
        calls.append('download')
        raise ConnectionError('offline')

    monkeypatch.setattr('fastembed.TextEmbedding', broken)
    m = InMemoryMemoryStore(LocalEmbedder('test', 2, 1, tmp_path))
    await m.add([item('python docs')])
    await m.add([item('python tests')])
    assert len(calls) == 1 and not m.verified
    assert len(await m.search(None, [GLOBAL], 'python')) == 2


async def test_remote_failure_falls_back_locally_with_correct_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Remote(OpenAICompatEmbedder):
        async def __call__(self, texts: list[str]) -> list[list[float]]:
            raise ConnectionError('remote down')

    class Engine:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def embed(self, texts: list[str], **kwargs: object):
            return [SimpleNamespace(tolist=lambda: [1.0, 0.0]) for _ in texts]

    monkeypatch.setattr('fastembed.TextEmbedding', Engine)
    remote = Remote(lambda: ('https://remote/v1', None), 'remote', 3072)
    routed = RoutedEmbedder(remote, LocalEmbedder('local', 2, 1, tmp_path))
    m = InMemoryMemoryStore(routed)
    saved = await m.add([item('python')])
    assert saved[0].embedding_model == 'local' and saved[0].embedding_dimensions == 2
    assert m.stats()['embedding_backend'] == 'local' and m.stats()['embedding_ready']


async def test_long_chinese_documents_include_the_tail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    class Engine:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def embed(self, texts: list[str], **kwargs: object):
            seen.extend(texts)
            return [SimpleNamespace(tolist=lambda: [1.0, 0.0]) for _ in texts]

    monkeypatch.setattr('fastembed.TextEmbedding', Engine)
    m = LocalEmbedder('test', 2, 1, tmp_path)
    assert await m(['中文' * 600 + '末尾证据']) == [[1.0, 0.0]]
    assert all(len(text) <= 400 for text in seen) and '末尾证据' in seen[-1]
