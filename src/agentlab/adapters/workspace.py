from __future__ import annotations

import asyncio
import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path

from agentlab.adapters.sandbox.local import run_argv, scrubbed_env
from agentlab.core.schemas import FileEdit


class WorkspaceEscape(PermissionError):
    pass


class GitWorkspace:
    def __init__(self, root: Path, secrets: tuple[str, ...] = ()) -> None:
        self.root = root.resolve()
        self._secrets = secrets
        self._baseline_tree: str | None = None
        self._baseline_meta: dict[str, tuple[str, str]] = {}
        self._edited_paths: set[str] = set()

    def _resolve(self, rel: str) -> Path:
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root):
            raise WorkspaceEscape(rel)
        if self._sensitive(rel) or self._sensitive(str(path.relative_to(self.root))):
            raise WorkspaceEscape("secret or reserved path")
        return path

    @staticmethod
    def _sensitive(rel: str) -> bool:
        parts = Path(rel.casefold()).parts
        return any(part.startswith(".env") or part in {
            ".git", ".agentlab", ".netrc", ".npmrc", "credentials.json", "secrets.json",
            "id_rsa", "id_ed25519", "node_modules", "__pycache__"
        } for part in parts) or Path(rel.casefold()).suffix in {".pem", ".key"}

    def _git_bytes(self, *args: str, data: bytes | None = None,
                   env: dict[str, str] | None = None) -> bytes:
        result = subprocess.run(["git", "-C", str(self.root), *args], input=data,
                                capture_output=True, check=True, env=env or scrubbed_env(), timeout=30)
        return result.stdout

    def _snapshot(self) -> tuple[str, dict[str, tuple[str, str]]]:
        """Capture working files in an isolated index; never alter the user's index."""
        paths = self._git_bytes("ls-files", "-z", "--cached", "--others", "--exclude-standard")
        names = set(os.fsdecode(paths).split("\0")) | self._edited_paths
        entries: list[bytes] = []
        metadata: dict[str, tuple[str, str]] = {}
        for rel in sorted(names):
            if not rel or self._sensitive(rel):
                continue
            candidate = self.root / rel
            if candidate.is_symlink():
                data = os.fsencode(os.readlink(candidate))
                mode, kind = "120000", "symlink"
            else:
                path = self._resolve(rel)
                if not path.exists():
                    continue  # A real deletion, unlike a filtered or unreadable file.
                if not path.is_file():
                    raise ValueError("unsupported workspace entry")
                data = path.read_bytes()  # Fail closed on unreadable files.
                mode = "100755" if path.stat().st_mode & 0o111 else "100644"
                try:
                    data.decode("utf-8")
                    binary = b"\0" in data
                except UnicodeError:
                    binary = True
                kind = "binary" if binary else "oversize" if len(data) > 100_000 else "text"
            if self._secret_text(data.decode("utf-8", errors="replace")):
                kind = "redacted-secret"
                # Never write detected secret contents into Git objects, even temporarily.
                data = ("[redacted secret content sha256=" + hashlib.sha256(data).hexdigest() + "]\n").encode()
            oid = self._git_bytes("hash-object", "-w", "--stdin", data=data).decode().strip()
            entries.append(f"{mode} {oid}\t".encode() + os.fsencode(rel) + b"\0")
            metadata[rel] = (oid, kind)
        with tempfile.TemporaryDirectory(prefix="agentlab-index-") as directory:
            env = {**scrubbed_env(), "GIT_INDEX_FILE": str(Path(directory) / "index")}
            self._git_bytes("read-tree", "--empty", env=env)
            self._git_bytes("update-index", "-z", "--index-info", data=b"".join(entries), env=env)
            tree = self._git_bytes("write-tree", env=env).decode().strip()
        return tree, metadata

    def _secret_text(self, text: str) -> bool:
        known_secret = any(secret in text for secret in self._secrets if secret)
        pattern = r"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY)"
        return known_secret or bool(re.search(pattern, text))

    def begin_run(self) -> None:
        self._baseline_tree, self._baseline_meta = self._snapshot()

    def read(self, path: str) -> str:
        return self._resolve(path).read_text()

    def apply_edits(self, edits: list[FileEdit]) -> list[str]:
        if any(len(edit.content.encode()) > 100_000 for edit in edits):
            raise ValueError("edit exceeds reviewable file size")
        if any(self._secret_text(edit.content) for edit in edits):
            raise WorkspaceEscape("edit contains secret material")
        targets = [(self._resolve(e.path), e) for e in edits]
        for path, edit in targets:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(edit.content)
        self._edited_paths.update(e.path for _, e in targets)
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
            if self._sensitive(rel):
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
            await self._git("-c", "user.name=agentlab", "-c", "user.email=agentlab@local",
                            "commit", "-q", "--allow-empty", "-m", "agentlab baseline")

    def _diff(self) -> str:
        current, metadata = self._snapshot()
        baseline = self._baseline_tree or self._git_bytes("mktree", data=b"").decode().strip()
        changed = os.fsdecode(self._git_bytes("diff", "--name-only", "-z", "--no-renames",
                                             baseline, current)).split("\0")
        parts: list[str] = []
        for path in changed:
            if not path:
                continue
            old_oid, old_kind = self._baseline_meta.get(path, ("absent", "text"))
            new_oid, new_kind = metadata.get(path, ("absent", "text"))
            if old_kind == new_kind == "text":
                parts.append(self._git_bytes("diff", "--no-ext-diff", "--no-textconv", "--no-renames",
                                             baseline, current, "--", ":(literal)" + path).decode())
            else:
                parts.append(f"diff --git a/{path} b/{path}\nchanged ({old_kind} -> {new_kind})\n"
                             f"old blob {old_oid}\nnew blob {new_oid}\n")
                parts.append(self._git_bytes("diff", "--raw", "--no-ext-diff", "--no-textconv", "--no-renames",
                                             baseline, current, "--", ":(literal)" + path).decode())
                # A formerly large/binary file rewritten as source must show its actual new contents.
                if new_kind == "text" and new_oid != "absent":
                    text = self._git_bytes("cat-file", "blob", new_oid).decode()
                    parts.append("Current file contents (baseline body omitted):\n" + text + "\n")
        return "".join(parts)

    async def diff(self) -> str:
        return await asyncio.to_thread(self._diff)
