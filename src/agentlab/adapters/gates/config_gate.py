from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from agentlab.core.config import GateCfg
from agentlab.core.ports import ExecResult, Sandbox
from agentlab.core.schemas import Diagnostic, GateMode, GateResult, GateStepResult

LOG_TAIL_CHARS = 4000
MAX_DIAGNOSTICS = 50

Parser = Callable[[str], list[Diagnostic]]

_FILE_LINE = re.compile(
    r"^(?P<file>[\w./\\-]+\.\w+):(?P<line>\d+)(?::(?P<col>\d+))?:?\s*"
    r"(?:(?P<code>[A-Z]+\d+|error|warning)\b:?)?\s*(?P<msg>.+)$",
    re.MULTILINE,
)
_TSC = re.compile(
    r"^(?P<file>[\w./\\-]+)\((?P<line>\d+),(?P<col>\d+)\):\s*error\s+(?P<code>TS\d+):\s*(?P<msg>.+)$", re.MULTILINE
)
_PYTEST = re.compile(r"^FAILED\s+(?P<file>[\w./\\-]+)::(?P<msg>.+)$", re.MULTILINE)


def _regex_parser(pattern: re.Pattern[str]) -> Parser:
    def parse(text: str) -> list[Diagnostic]:
        out = []
        for m in pattern.finditer(text):
            g = m.groupdict()
            out.append(Diagnostic(
                file=g["file"], line=int(g["line"]) if g.get("line") else None,
                col=int(g["col"]) if g.get("col") else None, code=g.get("code") or "", message=g["msg"].strip(),
            ))
        return out[:MAX_DIAGNOSTICS]
    return parse


PARSERS: dict[str, Parser] = {
    "tsc": _regex_parser(_TSC),
    "pytest": _regex_parser(_PYTEST),
}
DEFAULT_PARSER = _regex_parser(_FILE_LINE)


def parser_for(argv: list[str]) -> Parser:
    return next((p for tool, p in PARSERS.items() if tool in argv), DEFAULT_PARSER)


def step_result(name: str, argv: list[str], res: ExecResult, log_ref: str | None) -> GateStepResult:
    text = f"{res.stdout}\n{res.stderr}"
    passed = res.exit_code == 0
    return GateStepResult(
        name=name, passed=passed, exit_code=res.exit_code, duration_ms=res.duration_ms,
        diagnostics=[] if passed else parser_for(argv)(text),
        log_tail=text[-LOG_TAIL_CHARS:].strip(),
        truncated_log_ref=log_ref if len(text) > LOG_TAIL_CHARS else None,
    )


class ConfigGate:
    def __init__(self, cfg: GateCfg, sandbox: Sandbox, store_log: Callable[[str], str] | None = None) -> None:
        self.cfg = cfg
        self.language = cfg.language
        self._sandbox = sandbox
        self._store_log = store_log

    def detect(self, workspace: Path) -> bool:
        return any((workspace / m).exists() for m in self.cfg.markers)

    async def run(self, workspace: Path, mode: GateMode) -> GateResult:
        steps: list[GateStepResult] = []
        for step in (s for s in self.cfg.steps if mode in s.modes):
            res = await self._sandbox.exec(step.argv, workspace, step.timeout_s, image=self.cfg.image)
            text = f"{res.stdout}\n{res.stderr}"
            log_ref = self._store_log(text) if self._store_log and len(text) > LOG_TAIL_CHARS else None
            steps.append(step_result(step.name, step.argv, res, log_ref))
            if not steps[-1].passed:
                return GateResult(language=self.language, mode=mode, passed=False, steps=steps, failed_at=step.name)
        return GateResult(language=self.language, mode=mode, passed=True, steps=steps)


class NoGateDetected(LookupError):
    pass


def resolve_gate(gates: list[ConfigGate], workspace: Path, language: str | None = None) -> ConfigGate:
    if language:
        match = next((g for g in gates if g.language == language), None)
    else:
        match = next((g for g in gates if g.detect(workspace)), None)
    if match is None:
        raise NoGateDetected(language or str(workspace))
    return match
