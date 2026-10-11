from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from agentlab.adapters.sandbox.local import run_argv, scrubbed_env
from agentlab.core.ports import WorkspaceRootRequired, WorkspaceUnreadable
from agentlab.core.schemas import FileEdit


class WorkspaceEscape(PermissionError):
    kind = "workspace_escape"


class WorkspaceNotFound(FileNotFoundError):
    kind = "not_found"


class SourceUnavailable(ValueError):
    """An ordinary read failure (a directory, a large or binary file). The agent gets the error and can try
    another path; unlike WorkspaceEscape it is not a boundary violation and must not pause the run."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class PersistentDirectory:
    def __init__(self, path: Path) -> None:
        self.name = str(path.resolve())
        path.mkdir(parents=True, exist_ok=True, mode=0o700)

    def cleanup(self) -> None:
        shutil.rmtree(self.name, ignore_errors=True)


class GitWorkspace:
    def __init__(self, root: Path, secrets: tuple[str, ...] = (), snapshot_dir: Path | None = None) -> None:
        self.root = root.resolve()
        self._secrets = secrets
        self._baseline_tree: str | None = None
        self._baseline_meta: dict[str, tuple[str, str]] = {}
        self._edited_paths: set[str] = set()
        self._snapshot_dir = (
            PersistentDirectory(snapshot_dir)
            if snapshot_dir
            else tempfile.TemporaryDirectory(prefix="agentlab-objects-")
        )
        self._object_env: dict[str, str] | None = None
        self._present_repositories: set[str] = set()
        # Set when this workspace is a per-run worktree of the user's repository (see adapters/worktree.py).
        self.isolation: dict[str, str] | None = None

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
        return any(
            part.startswith(".env")
            or part
            in {
                ".git",
                ".agentlab",
                ".netrc",
                ".npmrc",
                "credentials.json",
                "secrets.json",
                "id_rsa",
                "id_ed25519",
                "node_modules",
                "__pycache__",
            }
            for part in parts
        ) or Path(rel.casefold()).suffix in {".pem", ".key"}

    def close(self) -> None:
        self._snapshot_dir.cleanup()

    def integrate_back(self) -> None:
        """Apply an isolated run's changes to the user's repository; raises WorktreeConflict."""
        if self.isolation:
            from agentlab.adapters.worktree import integrate

            integrate(self.isolation)

    def release(self) -> None:
        """Remove an isolated run's worktree and branch once the run has ended."""
        if self.isolation:
            from agentlab.adapters.worktree import remove

            remove(self.isolation)

    def export_state(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "snapshot_dir": self._snapshot_dir.name,
            "baseline_tree": self._baseline_tree,
            "baseline_meta": self._baseline_meta,
            "edited_paths": sorted(self._edited_paths),
            "present_repositories": sorted(self._present_repositories),
            "isolation": self.isolation,
        }

    def restore_state(self, state: dict[str, object]) -> None:
        if str(self.root) != state["root"]:
            raise ValueError("workspace root changed")
        self._baseline_tree = str(state["baseline_tree"])
        self._baseline_meta = {str(k): (str(v[0]), str(v[1])) for k, v in dict(state["baseline_meta"]).items()}  # type: ignore[call-overload]
        self._edited_paths = set(state["edited_paths"])  # type: ignore[call-overload]
        self._present_repositories = set(state["present_repositories"])  # type: ignore[call-overload]
        self.isolation = state.get("isolation")  # type: ignore[assignment]
        self._git_bytes("cat-file", "-e", self._baseline_tree)

    def _snapshot_env(self) -> dict[str, str]:
        if self._object_env is None:
            result = subprocess.run(
                ["git", "-C", str(self.root), "rev-parse", "--path-format=absolute", "--git-path", "objects"],
                capture_output=True,
                check=True,
                env=scrubbed_env(),
                timeout=30,
            )
            objects = Path(self._snapshot_dir.name) / "objects"
            objects.mkdir(exist_ok=True)
            self._object_env = {
                **scrubbed_env(),
                "GIT_OBJECT_DIRECTORY": str(objects),
                "GIT_ALTERNATE_OBJECT_DIRECTORIES": result.stdout.decode().strip(),
            }
        return self._object_env

    def _git_bytes(self, *args: str, data: bytes | None = None, env: dict[str, str] | None = None) -> bytes:
        result = subprocess.run(
            ["git", "-C", str(self.root), *args],
            input=data,
            capture_output=True,
            check=True,
            env=env or self._snapshot_env(),
            timeout=30,
        )
        return result.stdout

    def _snapshot(self) -> tuple[str, dict[str, tuple[str, str]]]:
        """Capture working files in an isolated index; never alter the user's index."""
        paths = self._git_bytes("ls-files", "-z", "--cached", "--others", "--exclude-standard")
        names = set(os.fsdecode(paths).split("\0")) | self._edited_paths
        entries: list[bytes] = []
        metadata: dict[str, tuple[str, str]] = {}
        stages = self._git_bytes("ls-files", "--stage", "-z")
        gitlinks = {
            os.fsdecode(path): header.split()[1].decode()
            for item in stages.split(b"\0")
            if item
            for header, path in [item.split(b"\t", 1)]
            if header.startswith(b"160000 ")
        }
        repository_roots = set(gitlinks) | {name.rstrip("/") for name in names if name and (self.root / name).is_dir()}
        with tempfile.TemporaryDirectory(prefix="agentlab-index-") as directory:
            pending: list[tuple[str, str, str, Path]] = []
            for rel in sorted(names):
                rel = rel.rstrip("/")
                if not rel or self._sensitive(rel) or any(rel.startswith(root + "/") for root in repository_roots):
                    continue
                candidate = self.root / rel
                if candidate.is_symlink():
                    data = os.fsencode(os.readlink(candidate))
                    mode, kind = "120000", "symlink"
                else:
                    path = self._resolve(rel)
                    if rel in gitlinks and not path.exists() and rel in self._present_repositories:
                        continue
                    if path.is_dir() or (rel in gitlinks and not path.exists()):
                        if path.exists():
                            self._present_repositories.add(rel)
                        # Gitlinks can refer to commits absent from the parent object database.
                        oid = gitlinks.get(rel)
                        if (path / ".git").exists():
                            head = subprocess.run(
                                ["git", "-C", str(path), "rev-parse", "--verify", "HEAD"],
                                capture_output=True,
                                env=scrubbed_env(),
                                timeout=30,
                            )
                            if head.returncode == 0:
                                oid = head.stdout.decode().strip()
                        if oid:
                            entries.append(f"160000 {oid}\t".encode() + os.fsencode(rel) + b"\0")
                            kind = "submodule"
                            if (path / ".git").exists():
                                status = subprocess.run(
                                    ["git", "-C", str(path), "status", "--porcelain", "-z"],
                                    capture_output=True,
                                    check=True,
                                    env=scrubbed_env(),
                                    timeout=30,
                                )
                                if status.stdout:
                                    patch = subprocess.run(
                                        [
                                            "git",
                                            "-C",
                                            str(path),
                                            "diff",
                                            "--no-ext-diff",
                                            "--no-textconv",
                                            "--binary",
                                            "HEAD",
                                        ],
                                        capture_output=True,
                                        check=True,
                                        env=scrubbed_env(),
                                        timeout=30,
                                    )
                                    dirty = status.stdout + patch.stdout
                                    for edited in sorted(self._edited_paths):
                                        if edited.startswith(rel + "/") and (self.root / edited).is_file():
                                            dirty += (self.root / edited).read_bytes()
                                    kind = "submodule-dirty sha256=" + hashlib.sha256(dirty).hexdigest()
                            metadata[rel] = (oid, kind)
                            continue
                        # An unborn embedded repository is visible, rather than blocking creation.
                        unborn = b""
                        for edited in sorted(self._edited_paths):
                            if edited.startswith(rel + "/") and (self.root / edited).is_file():
                                unborn += (self.root / edited).read_bytes()
                        data = (
                            "[embedded repository without HEAD; edited content sha256="
                            + hashlib.sha256(unborn).hexdigest()
                            + "]\n"
                        ).encode()
                        mode, kind = "100644", "embedded-unborn"
                    else:
                        if not path.exists():
                            continue
                        if not path.is_file():
                            raise WorkspaceUnreadable("unsupported workspace entry")
                        try:
                            data = path.read_bytes()
                            mode = "100755" if path.stat().st_mode & 0o111 else "100644"
                        except OSError as exc:
                            raise WorkspaceUnreadable("workspace file unreadable") from exc
                        try:
                            data.decode("utf-8")
                            binary = b"\0" in data
                        except UnicodeError:
                            binary = True
                        kind = "binary" if binary else "oversize" if len(data) > 100_000 else "text"
                if self._secret_text(data.decode("utf-8", errors="replace")):
                    kind = "redacted-secret"
                    data = ("[redacted secret content sha256=" + hashlib.sha256(data).hexdigest() + "]\n").encode()
                sanitized = Path(directory) / str(len(pending))
                sanitized.write_bytes(data)
                pending.append((rel, mode, kind, sanitized))
            if pending:
                # Sanitized copies avoid Git filters and prevent secrets entering even temporary blobs.
                paths = b"".join(os.fsencode(path) + b"\n" for _, _, _, path in pending)
                owned_env = {k: v for k, v in self._snapshot_env().items() if k != "GIT_ALTERNATE_OBJECT_DIRECTORIES"}
                oids = self._git_bytes(
                    "hash-object", "-w", "--no-filters", "--stdin-paths", data=paths, env=owned_env
                ).splitlines()
                if len(oids) != len(pending):
                    raise RuntimeError("incomplete batch hashing")
                for (rel, mode, kind, _), batch_oid in zip(pending, oids, strict=True):
                    entries.append(f"{mode} ".encode() + batch_oid + b"\t" + os.fsencode(rel) + b"\0")
                    metadata[rel] = (batch_oid.decode(), kind)
            env = {k: v for k, v in self._snapshot_env().items() if k != "GIT_ALTERNATE_OBJECT_DIRECTORIES"}
            env["GIT_INDEX_FILE"] = str(Path(directory) / "index")
            self._git_bytes("read-tree", "--empty", env=env)
            self._git_bytes("update-index", "-z", "--index-info", data=b"".join(entries), env=env)
            tree = self._git_bytes("write-tree", env=env).decode().strip()
        return tree, metadata

    def _secret_text(self, text: str) -> bool:
        known_secret = any(secret in text for secret in self._secrets if secret)
        pattern = r"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY)"
        return known_secret or bool(re.search(pattern, text))

    def begin_run(self) -> None:
        self._present_repositories.clear()
        self._baseline_tree, self._baseline_meta = self._snapshot()

    def read(self, path: str) -> str:
        return self._resolve(path).read_text()

    def apply_edits(self, edits: list[FileEdit]) -> list[str]:
        if any(len(edit.content.encode()) > 100_000 for edit in edits):
            raise ValueError("edit exceeds reviewable file size")
        if any(self._secret_text(edit.content) for edit in edits):
            raise WorkspaceEscape("edit contains secret material")
        targets = [(self._resolve(e.path), e) for e in edits]
        stages = self._git_bytes("ls-files", "--stage", "-z")
        gitlinks = {
            os.fsdecode(item.split(b"\t", 1)[1]).casefold()
            for item in stages.split(b"\0")
            if item.startswith(b"160000 ")
        }
        for path, _ in targets:
            rel = path.relative_to(self.root).as_posix().casefold()
            if any(rel == link or rel.startswith(link + "/") for link in gitlinks):
                raise WorkspaceEscape("nested repository requires its own project")
            for parent in (path, *path.parents):
                if parent == self.root:
                    break
                if (parent / ".git").exists() or (
                    (parent / "HEAD").is_file() and (parent / "objects").is_dir() and (parent / "refs").is_dir()
                ):
                    raise WorkspaceEscape("nested repository requires its own project")
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

    async def source_files(self) -> list[str]:
        try:
            paths = (await self._git("ls-files", "-z", "--cached", "--others", "--exclude-standard")).split("\0")
        except RuntimeError:
            # Read-only conversations also work before a project has been initialized as Git.
            paths = []
            for directory, dirs, names in os.walk(self.root, followlinks=False):
                dirs[:] = [
                    name for name in dirs if not self._sensitive(name) and not (Path(directory) / name).is_symlink()
                ]
                paths.extend((Path(directory) / name).relative_to(self.root).as_posix() for name in names)
                if len(paths) >= 5000:
                    break
        files = []
        for rel in sorted(set(paths)):
            if not rel or (self.root / rel).is_symlink():
                continue
            try:
                path = self._resolve(rel)
                if path.is_file():
                    files.append(rel)
            except (OSError, WorkspaceEscape):
                continue
            if len(files) >= 5000:
                break
        return files

    def read_source(self, rel: str, line_start: int = 1, line_end: int | None = None) -> str:
        # Dependencies are excluded from source tools, but asking to inspect one
        # is an ordinary unsupported read, not a request to escape the workspace.
        # Resolve first so an external dependency symlink still stops the run.
        if "node_modules" in Path(rel.casefold()).parts:
            if not (self.root / rel).resolve().is_relative_to(self.root):
                raise WorkspaceEscape(rel)
            raise SourceUnavailable("excluded_dependency_directory: use project source or API documentation")
        path = self._resolve(rel)
        if not path.exists() and not (self.root / rel).is_symlink():
            raise WorkspaceNotFound(f"source file not found: {rel}")
        if (self.root / rel).is_symlink():
            raise WorkspaceEscape("unreadable source")
        if path.is_dir():
            raise SourceUnavailable("is_directory: read a file inside it, or use an empty path to list files")
        if not path.is_file():
            raise SourceUnavailable("not_a_regular_file")
        if path.stat().st_size > 100_000:
            raise SourceUnavailable("file_too_large")
        try:
            text = self.read(rel)
        except UnicodeDecodeError as exc:
            raise SourceUnavailable("binary_file") from exc
        if "\0" in text:
            raise SourceUnavailable("binary_file")
        if self._secret_text(text):
            raise WorkspaceEscape("secret content")
        if line_start < 1 or (line_end is not None and line_end < line_start):
            raise ValueError("invalid line range")
        lines = text.splitlines(keepends=True)
        end = min(line_end if line_end is not None else line_start + 199, len(lines))
        selected = "".join(lines[line_start - 1:end])
        encoded = selected.encode()
        if len(encoded) > 12000:
            return encoded[:12000].decode(errors="ignore") + "\n[truncated; request a smaller line range]"
        if end < len(lines):
            selected += f"\n[more lines; continue with line_start={end + 1}; total_lines={len(lines)}]"
        return selected

    async def inspect_git(self, command: str, ref: str = "", path: str = "") -> str:
        """Fixed read-only commands; callers cannot supply Git options or shell code."""
        if command not in {"status", "log", "branch", "diff", "show"}:
            raise ValueError("unsupported Git inspection")
        if ref and not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./@~^+-]*", ref):
            raise ValueError("invalid Git revision")
        if path:
            self._resolve(path)
            if Path(path).is_absolute() or ".." in Path(path).parts:
                raise WorkspaceEscape(path)
        base = ["--no-pager", "--no-optional-locks"]
        if command == "status":
            args = ["status", "--short", "--untracked-files=normal"]
        elif command == "branch":
            args = ["branch", "--all", "--no-color"]
        elif command == "log":
            args = ["log", "-30", "--format=%h %d %s", ref or "HEAD", "--"]
        elif command == "show":
            revision = ref or "HEAD"
            if path:
                args = ["show", "--no-ext-diff", "--no-textconv", f"{revision}:{path}"]
            else:
                args = ["ls-tree", "-r", "--name-only", revision, "--"]
        else:
            args = ["diff", "--no-ext-diff", "--no-textconv", "--no-color"]
            if not path:
                args += ["--name-only"]
            if ref:
                args += [ref]
            args += ["--"]
            if path:
                args += [":(literal)" + path]
        output = await self._git(*base, *args)
        if (command == "show" and not path) or (command == "diff" and not path):
            output = "\n".join(line for line in output.splitlines() if not self._sensitive(line))
        if command == "status":
            output = "\n".join(line for line in output.splitlines() if not self._sensitive(line[3:]))
        if "\0" in output or self._secret_text(output):
            raise WorkspaceEscape("secret or binary Git content")
        return output[:12000] + ("\n[truncated]" if len(output) > 12000 else "")

    async def context_files(self) -> dict[str, str]:
        """Bounded source context; never include secret files, symlinks or binaries."""
        paths = (await self._git("ls-files", "-z", "--cached", "--others", "--exclude-standard")).split("\0")
        files: dict[str, str] = {}
        remaining = 64_000
        for rel in sorted(set(paths)):
            if not rel or len(files) >= 40 or remaining <= 0:
                continue
            parts = Path(rel).parts
            if any(part.startswith(".") or part in {"node_modules", "dist", "venv", "__pycache__"} for part in parts):
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
        top = await run_argv(["git", "-C", str(self.root), "rev-parse", "--show-toplevel"], None, 30, scrubbed_env())
        if top.exit_code == 0 and Path(top.stdout.strip()).resolve() != self.root:
            raise WorkspaceRootRequired("workspace must point to the existing repository root")
        if top.exit_code not in (0, 128):
            raise RuntimeError("cannot detect repository root")
        if not (self.root / ".git").exists():
            await self._git("init", "-q")
            await self._git(
                "-c",
                "user.name=agentlab",
                "-c",
                "user.email=agentlab@local",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "agentlab baseline",
            )

    def _diff(self) -> str:
        current, metadata = self._snapshot()
        baseline = self._baseline_tree or self._git_bytes("mktree", data=b"").decode().strip()
        changed = os.fsdecode(self._git_bytes("diff", "--name-only", "-z", "--no-renames", baseline, current)).split(
            "\0"
        )
        changed = sorted(
            set(changed)
            | {
                path
                for path in metadata.keys() & self._baseline_meta.keys()
                if metadata[path] != self._baseline_meta[path]
            }
        )
        parts: list[str] = []
        for path in changed:
            if not path:
                continue
            old_oid, old_kind = self._baseline_meta.get(path, ("absent", "text"))
            new_oid, new_kind = metadata.get(path, ("absent", "text"))
            if old_kind == new_kind == "text":
                parts.append(
                    self._git_bytes(
                        "diff",
                        "--no-ext-diff",
                        "--no-textconv",
                        "--no-renames",
                        baseline,
                        current,
                        "--",
                        ":(literal)" + path,
                    ).decode()
                )
            else:
                parts.append(
                    f"diff --git a/{path} b/{path}\nchanged ({old_kind} -> {new_kind})\n"
                    f"old blob {old_oid}\nnew blob {new_oid}\n"
                )
                parts.append(
                    self._git_bytes(
                        "diff",
                        "--raw",
                        "--no-ext-diff",
                        "--no-textconv",
                        "--no-renames",
                        baseline,
                        current,
                        "--",
                        ":(literal)" + path,
                    ).decode()
                )
                # A formerly large/binary file rewritten as source must show its actual new contents.
                if new_kind == "text" and new_oid != "absent":
                    text = self._git_bytes("cat-file", "blob", new_oid).decode()
                    parts.append("Current file contents (baseline body omitted):\n" + text + "\n")
        return "".join(parts)

    async def diff(self) -> str:
        return await asyncio.to_thread(self._diff)
