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
    paragraphs = [p.strip() for p in normalize(text).split("\n\n") if p.strip()]
    buf = ""
    for p in paragraphs:
        while len(p) > size:
            if buf:
                yield buf
                buf = ""
            yield p[:size]
            p = p[size - overlap:]
        if len(buf) + len(p) + 2 > size and buf:
            yield buf
            buf = buf[-overlap:] + "\n\n" + p if overlap else p
        else:
            buf = f"{buf}\n\n{p}" if buf else p
    if buf:
        yield buf
