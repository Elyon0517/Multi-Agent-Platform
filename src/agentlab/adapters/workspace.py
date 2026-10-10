from __future__ import annotations

import difflib
import re
import subprocess
from pathlib import Path

from agentlab.adapters.sandbox.local import run_argv, scrubbed_env
from agentlab.core.schemas import FileEdit


class WorkspaceEscape(PermissionError):
    pass


class GitWorkspace:
    def __init__(self, root: Path, secrets: tuple[str, ...] = ()) -> None:
        self.root = root.resolve()
        self._secrets = secrets
        self._baseline: dict[str, str] = {}

    def _resolve(self, rel: str) -> Path:
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root) or ".git" in path.relative_to(self.root).parts:
            raise WorkspaceEscape(rel)
        if self._sensitive(rel):
            raise WorkspaceEscape("secret or reserved path")
        return path

    @staticmethod
    def _sensitive(rel: str) -> bool:
        parts = Path(rel).parts
        return any(part.startswith(".env") or part in {
            ".git", ".agentlab", ".netrc", ".npmrc", "id_rsa", "id_ed25519", "node_modules", "__pycache__"
        }
                   for part in parts) or any(word in Path(rel).name.lower()
                   for word in ("secret", "credential", "private", ".pem", ".key"))

    def _snapshot(self) -> dict[str, str]:
        result = subprocess.run(["git", "-C", str(self.root), "ls-files", "-z", "--cached", "--others",
                                 "--exclude-standard"], capture_output=True, check=True, env=scrubbed_env())
        snapshot = {}
        for rel in sorted(set(result.stdout.decode().split("\0"))):
            if not rel or self._sensitive(rel) or (self.root / rel).is_symlink():
                continue
            try:
                path = self._resolve(rel)
                if not path.is_file() or path.stat().st_size > 100_000:
                    continue
                text = path.read_text()
                if "\0" not in text and not self._secret_text(text):
                    snapshot[rel] = text
            except (OSError, UnicodeError, WorkspaceEscape):
                continue
        return snapshot

    def _secret_text(self, text: str) -> bool:
        known_secret = any(secret in text for secret in self._secrets if secret)
        pattern = r"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY)"
        return known_secret or bool(re.search(pattern, text))

    def begin_run(self) -> None:
        self._baseline = self._snapshot()

    def read(self, path: str) -> str:
        return self._resolve(path).read_text()

    def apply_edits(self, edits: list[FileEdit]) -> list[str]:
        if any(len(edit.content.encode()) > 100_000 for edit in edits):
            raise ValueError("edit exceeds reviewable file size")
        targets = [(self._resolve(e.path), e) for e in edits]
        for path, edit in targets:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(edit.content)
        return [e.path for _, e in targets]

    async def _git(self, *args: str) -> str:
        res = await run_argv(["git", "-C", str(self.root), *args], None, 60, scrubbed_env())
        if res.exit_code != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
        return res.stdout

    async def context_files(self) -> dict[str, str]:
        """Bounded source context; never include secret files, symlinks or binaries."""
        paths = (await self._git("ls-files", "-z", "--cached", "--others", "--exclude-standard")).split("\0")
        files: dict[str, str] = {}
        remaining = 64_000
        for rel in sorted(set(paths)):
            if not rel or len(files) >= 40 or remaining <= 0:
                continue
            parts = Path(rel).parts
            if any(part.startswith(".") or part in {"node_modules", "dist", "venv", "__pycache__"}
                   for part in parts):
                continue
            if any(word in Path(rel).name.lower() for word in ("secret", "credential", "private", ".pem", ".key")):
                continue
            candidate = self.root / rel
            if candidate.is_symlink():
                continue
            try:
                path = self._resolve(rel)
                if not path.is_file() or path.stat().st_size > 100_000:
                    continue
                text = path.read_text()
            except (OSError, UnicodeError, WorkspaceEscape):
                continue
            if "\0" in text or self._secret_text(text):
                continue
            limit = min(12_000, remaining)
            files[rel] = text[:limit] + ("\n[truncated]" if len(text) > limit else "")
            remaining -= len(files[rel])
        return files

    async def ensure_repo(self) -> None:
        if not (self.root / ".git").exists():
            await self._git("init", "-q")
            paths = list(self._snapshot())
            if paths:
                await self._git("add", "--", *paths)
            await self._git("-c", "user.name=agentlab", "-c", "user.email=agentlab@local",
                            "commit", "-q", "--allow-empty", "-m", "agentlab baseline")

    async def diff(self) -> str:
        current = self._snapshot()
        return "".join(
            "".join(difflib.unified_diff(self._baseline.get(path, "").splitlines(keepends=True),
                                       current.get(path, "").splitlines(keepends=True),
                                       fromfile=f"a/{path}", tofile=f"b/{path}"))
            for path in sorted(self._baseline.keys() | current.keys())
            if self._baseline.get(path) != current.get(path)
        )
