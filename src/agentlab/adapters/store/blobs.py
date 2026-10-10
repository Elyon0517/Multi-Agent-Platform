from __future__ import annotations

import hashlib
from pathlib import Path


class FileBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        root.mkdir(parents=True, exist_ok=True)

    def put(self, content: str) -> tuple[str, str]:
        sha = hashlib.sha256(content.encode()).hexdigest()
        path = self._root / sha[:2] / sha
        if not path.exists():
            path.parent.mkdir(exist_ok=True)
            path.write_text(content)
        return f"blob://{sha}", sha

    def get(self, ref: str) -> str:
        sha = ref.removeprefix("blob://")
        return (self._root / sha[:2] / sha).read_text()
