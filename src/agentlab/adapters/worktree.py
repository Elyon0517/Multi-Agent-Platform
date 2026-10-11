"""Per-run Git worktrees.

Every run works on its own checkout of the user's repository, so several runs (including runs paused
for approval) can proceed in the same project without touching each other's files. The checkout starts
from the user's current state, uncommitted changes included. On signoff approval only the run's own
changes are applied back to the user's working tree; if they no longer apply cleanly nothing is touched.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from agentlab.adapters.sandbox.local import scrubbed_env

# Commits made here are bookkeeping on a throwaway branch: no user identity, hooks or signing.
_COMMIT = ["-c", "user.name=agentlab", "-c", "user.email=agentlab@local", "-c", "commit.gpgsign=false"]


class WorktreeConflict(ValueError):
    """The run's changes no longer apply to the user's working tree."""


def _git(cwd: Path, *args: str, data: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], input=data, capture_output=True, check=check, env=scrubbed_env(), timeout=120
    )


def can_isolate(repo: Path) -> bool:
    """Worktrees need a repository root with at least one commit."""
    top = _git(repo, "rev-parse", "--show-toplevel", check=False)
    head = _git(repo, "rev-parse", "--verify", "-q", "HEAD", check=False)
    is_root = top.returncode == 0 and Path(top.stdout.decode().strip()).resolve() == repo.resolve()
    return is_root and head.returncode == 0


def _commit(path: Path, message: str) -> str:
    _git(path, "add", "-A")
    _git(path, *_COMMIT, "commit", "-q", "--allow-empty", "--no-verify", "-m", message)
    return _git(path, "rev-parse", "HEAD").stdout.decode().strip()


def create(repo: Path, path: Path, run_id: str) -> dict[str, str]:
    repo, branch = repo.resolve(), f"agentlab/{run_id}"
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-q", "-b", branch, str(path), "HEAD")
    try:
        # Carry the user's uncommitted work, so agents see the same code the user does.
        tracked = _git(repo, "diff", "--binary", "HEAD").stdout
        if tracked.strip():
            _git(path, "apply", "--binary", "--whitespace=nowarn", data=tracked)
        untracked = _git(repo, "ls-files", "-z", "--others", "--exclude-standard").stdout.decode().split("\0")
        for rel in filter(None, untracked):
            source, target = repo / rel, path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target, follow_symlinks=False)
        base = _commit(path, f"agentlab base for run {run_id}")
    except Exception:
        remove({"repo": str(repo), "path": str(path), "branch": branch})
        raise
    return {"repo": str(repo), "path": str(path.resolve()), "branch": branch, "base": base, "run_id": run_id}


def integrate(info: dict[str, str]) -> None:
    """Apply the run's changes (base → final) to the user's working tree, uncommitted, or raise."""
    path, repo = Path(info["path"]), Path(info["repo"])
    final = _commit(path, f"agentlab run {info['run_id']}")
    patch = _git(path, "diff", "--binary", info["base"], final).stdout
    if not patch.strip():
        return
    if _git(repo, "apply", "--check", "--binary", data=patch, check=False).returncode == 0:
        _git(repo, "apply", "--binary", "--whitespace=nowarn", data=patch)
        return
    # Already applied by hand after an earlier conflict: approving again just completes the run.
    if _git(repo, "apply", "--check", "--reverse", "--binary", data=patch, check=False).returncode == 0:
        return
    files = _git(path, "diff", "--name-only", info["base"], final).stdout.decode().split()
    raise WorktreeConflict(
        f"the run's changes conflict with your working tree ({', '.join(files[:10])}); "
        f"merge branch {info['branch']} yourself, then approve again"
    )


def remove(info: dict[str, str]) -> None:
    repo, path = Path(info["repo"]), Path(info["path"])
    _git(repo, "worktree", "remove", "--force", str(path), check=False)
    shutil.rmtree(path, ignore_errors=True)
    _git(repo, "worktree", "prune", check=False)
    _git(repo, "branch", "-D", info["branch"], check=False)
