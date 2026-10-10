from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

SECRET_KEYS = ("AGENTLAB_LLM_API_KEY", "AGENTLAB_EMBEDDING_API_KEY")
PLAIN_KEYS = ("AGENTLAB_LLM_BASE_URL", "AGENTLAB_EMBEDDING_BASE_URL")
EDITABLE = (*SECRET_KEYS, *PLAIN_KEYS)
_LINE = re.compile(r"^\s*([A-Z0-9_]+)\s*=\s*(.*)$")


class SettingView(BaseModel):
    key: str
    secret: bool
    is_set: bool
    display: str


def mask(value: str) -> str:
    if not value:
        return ""
    return "\u2022" * 8 + value[-4:] if len(value) > 8 else "\u2022" * 8


class EnvFile:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        out = {}
        for line in self.path.read_text().splitlines():
            if m := _LINE.match(line):
                out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
        return out

    def update(self, values: dict[str, str]) -> None:
        unknown = set(values) - set(EDITABLE)
        if unknown:
            raise KeyError(f"not editable: {sorted(unknown)}")
        if any("\n" in v or "\r" in v for v in values.values()):
            raise ValueError("values must be single-line")
        lines = self.path.read_text().splitlines() if self.path.exists() else []
        pending = dict(values)
        for i, line in enumerate(lines):
            if (m := _LINE.match(line)) and m.group(1) in pending:
                lines[i] = f"{m.group(1)}={pending.pop(m.group(1))}"
        lines += [f"{k}={v}" for k, v in pending.items()]
        self.path.write_text("\n".join(lines) + "\n")
        self.path.chmod(0o600)


def views(current: dict[str, str | None]) -> list[SettingView]:
    return [
        SettingView(key=k, secret=k in SECRET_KEYS, is_set=bool(current.get(k)),
                    display=mask(current.get(k) or "") if k in SECRET_KEYS else current.get(k) or "")
        for k in EDITABLE
    ]
