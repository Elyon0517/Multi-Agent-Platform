from __future__ import annotations

import re
from collections.abc import Iterator
from io import BytesIO

from pypdf import PdfReader

CHUNK_CHARS = 1200
OVERLAP_CHARS = 150


class UnsupportedDocument(ValueError):
    pass


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        text = "\n\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages)
        if not text.strip():
            raise UnsupportedDocument(f"{filename}: no extractable text (scanned PDF?)")
        return text
    if name.endswith((".md", ".txt", ".markdown")):
        return data.decode("utf-8", errors="replace")
    raise UnsupportedDocument(f"{filename}: only .pdf, .md, .txt are supported")


def normalize(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def chunk(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> Iterator[str]:
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("require size > 0 and 0 <= overlap < size")
    normalized = normalize(text)
    start = 0
    while start < len(normalized):
        end = min(start + size, len(normalized))
        yield normalized[start:end]
        if end == len(normalized):
            break
        start = end - overlap
