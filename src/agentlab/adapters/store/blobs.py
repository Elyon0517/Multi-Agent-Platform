from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


class FileBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def put(self, content: str) -> tuple[str, str]:
        sha = hashlib.sha256(content.encode()).hexdigest()
        path = self._root / sha[:2] / sha
        if not path.exists():
            path.parent.mkdir(exist_ok=True, mode=0o700)
            fd, temporary = tempfile.mkstemp(dir=path.parent)
            try:
                # Journal content hashes describe UTF-8 bytes, including original line endings.
                with os.fdopen(fd, "wb") as handle:
                    handle.write(content.encode("utf-8"))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return f"blob://{sha}", sha

    def get(self, ref: str) -> str:
        sha = ref.removeprefix("blob://")
        return (self._root / sha[:2] / sha).read_bytes().decode("utf-8")
