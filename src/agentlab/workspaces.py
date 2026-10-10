from pathlib import Path


def evaluation_workspace_root() -> Path:
    """Host-visible workspaces outside the application checkout (including Colima)."""
    root = Path.home() / ".agentlab-workspaces"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root
