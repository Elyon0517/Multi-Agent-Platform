"""Private Harness copies. Only validated text deltas may cross back through EditJournal."""
from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

from agentlab.adapters.workspace import GitWorkspace, WorkspaceEscape
from agentlab.core.ports import EditConflict
from agentlab.core.schemas import FileEdit


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class HarnessWorkspace:
    caches = {"__pycache__", "node_modules", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv"}

    def __init__(self, workspace: GitWorkspace, directory: Path) -> None:
        self.workspace = workspace
        self.directory = directory
        self.root = directory / "source"

    @staticmethod
    def excluded(path: str) -> bool:
        return GitWorkspace._sensitive(path) or any(
            part in {".claude", ".codex", ".mcp.json", *HarnessWorkspace.caches} for part in Path(path).parts
        )

    def create(self, expected_revision: str, baseline: dict[str, str] | None = None) -> dict[str, Any]:
        if self.directory.exists():
            raise ValueError("harness directory already exists")
        # Materialize immutable objects from the very tree used for the revision identity.
        # Live per-file reads between two matching captures can otherwise copy a transient B in A -> B -> A.
        tree, metadata = self.workspace._snapshot()
        before = self.workspace._revision_id(tree, metadata)
        if before != expected_revision:
            raise EditConflict("harness_source_changed", [])
        self.directory.mkdir(parents=True, mode=0o700)
        self.root.mkdir(mode=0o700)
        manifest: dict[str, Any] = {}
        entries = self.workspace._git_bytes("ls-tree", "-r", "-z", tree)
        for entry in entries.split(b"\0"):
            if not entry:
                continue
            header, raw_path = entry.split(b"\t", 1)
            mode, kind, oid = header.decode().split()
            rel = os.fsdecode(raw_path)
            if self.excluded(rel):
                continue
            if kind != "blob" or mode not in {"100644", "100755"} or metadata[rel][1] not in {
                "text", "binary", "oversize",
            }:
                raise WorkspaceEscape("harness source contains unsupported or secret material")
            data = self.workspace._git_bytes("cat-file", "blob", oid)
            if baseline is not None and baseline.get(rel) != digest(data):
                raise EditConflict("harness_source_changed", [rel])
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            executable = mode == "100755"
            target.chmod(0o755 if executable else 0o644)
            manifest[rel] = {"hash": digest(data), "executable": executable}
        if self.workspace.review_snapshot()[0] != before:
            raise EditConflict("harness_source_changed", [])
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.directory),
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        subprocess.run(["git", "init", "--quiet", "--template=", str(self.root)], check=True,
                       capture_output=True, env=env, timeout=30)
        git = ["git", "-C", str(self.root), "-c", "core.hooksPath=" + os.devnull,
               "-c", "commit.gpgsign=false", "-c", "user.name=AgentLab", "-c", "user.email=agentlab@localhost"]
        subprocess.run([*git, "add", "--force", "--all"], check=True, capture_output=True, env=env, timeout=30)
        subprocess.run([*git, "commit", "--quiet", "--allow-empty", "--no-verify", "-m", "Harness input"],
                       check=True, capture_output=True, env=env, timeout=30)
        return manifest

    def scan(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if not self.root.is_dir() or self.root.is_symlink():
            raise WorkspaceEscape("harness source replaced")
        for directory, dirs, files in os.walk(self.root, followlinks=False):
            current = Path(directory)
            if current != self.root and ((current / ".git").exists() or (
                (current / "HEAD").is_file() and (current / "objects").is_dir() and (current / "refs").is_dir()
            )):
                raise WorkspaceEscape("harness output contains nested repository")
            for ignored in {".git", *self.caches}:
                if ignored in dirs:
                    if (Path(directory) / ignored).is_symlink():
                        raise WorkspaceEscape("harness output contains symlink")
                    dirs.remove(ignored)
            for name in [*dirs, *files]:
                path = Path(directory) / name
                rel = path.relative_to(self.root).as_posix()
                if path.is_symlink():
                    raise WorkspaceEscape("harness output contains symlink")
                if self.excluded(rel):
                    raise WorkspaceEscape("harness output contains reserved path")
                if path.is_dir():
                    continue
                if not path.is_file():
                    raise WorkspaceEscape("harness output contains special file")
                result[rel] = {"hash": digest(path.read_bytes()),
                               "executable": bool(path.stat().st_mode & stat.S_IXUSR)}
        return result

    def edits(self, baseline: dict[str, Any]) -> tuple[list[FileEdit], dict[str, Any]]:
        current = self.scan()
        if baseline.keys() - current.keys():
            raise ValueError("harness deletions and renames are not supported")
        edits = []
        for rel, entry in current.items():
            previous = baseline.get(rel)
            if previous == entry:
                continue
            if entry["executable"] != (previous or {"executable": False})["executable"]:
                raise ValueError("harness mode changes are not supported")
            data = (self.root / rel).read_bytes()
            if digest(data) != entry["hash"]:
                raise EditConflict("harness_copy_changed", [rel])
            content = data.decode("utf-8")
            if "\0" in content:
                raise ValueError("harness binary edits are not supported")
            edits.append(FileEdit(path=rel, content=content))
        return self.workspace.validate_edits(sorted(edits, key=lambda e: e.path)), current

    def read_only(self) -> None:
        for directory, _dirs, files in os.walk(self.root, topdown=False):
            for name in files:
                path = Path(directory) / name
                path.chmod(0o555 if path.stat().st_mode & stat.S_IXUSR else 0o444)
            Path(directory).chmod(0o555)
