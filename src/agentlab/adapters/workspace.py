from __future__ import annotations

from pathlib import Path

from agentlab.adapters.sandbox.local import run_argv, scrubbed_env
from agentlab.core.schemas import FileEdit


class WorkspaceEscape(PermissionError):
    pass


class GitWorkspace:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _resolve(self, rel: str) -> Path:
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root) or ".git" in path.relative_to(self.root).parts:
            raise WorkspaceEscape(rel)
        return path

    def read(self, path: str) -> str:
        return self._resolve(path).read_text()

    def apply_edits(self, edits: list[FileEdit]) -> list[str]:
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

    async def ensure_repo(self) -> None:
        if not (self.root / ".git").exists():
            await self._git("init", "-q")
            await self._git("add", "-A")
            await self._git("-c", "user.name=agentlab", "-c", "user.email=agentlab@local",
                            "commit", "-q", "--allow-empty", "-m", "agentlab baseline")

    async def diff(self) -> str:
        await self._git("add", "-A", "--intent-to-add")
        return await self._git("diff", "--no-color")
