from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from agentlab.core.config import GateCfg, GateStepCfg
from agentlab.core.project import PhasePlan, ProjectPlan
from agentlab.core.schemas import (
    AgentInput,
    CoderOutput,
    FileEdit,
    Finding,
    GateMode,
    Plan,
    Severity,
    Verdict,
)

DEMO_FILES = {
    "pyproject.toml": '[project]\nname = "demo"\nversion = "0.0.0"\n',
    "calc.py": "def add(a, b):\n    return a - b\n",
    "test_calc.py": "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
}


def seed_demo_workspace(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, content in DEMO_FILES.items():
        (root / name).write_text(content)
    return root


def demo_gate_cfg() -> GateCfg:
    return GateCfg(language="python", image="python:3.12-slim", markers=["pyproject.toml"], steps=[
        GateStepCfg(name="test", argv=[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                    timeout_s=120, modes=[GateMode.FAST, GateMode.FULL]),
    ])


def _plan(_: AgentInput) -> BaseModel:
    return Plan(summary="fix add", steps=["return a + b"], acceptance_criteria=["test_add passes"])


def _coder(inp: AgentInput) -> BaseModel:
    body = "    return a + b\n" if inp.iteration >= 2 else "    return a * b\n"
    if inp.instructions:
        body = '    """Add two numbers."""\n    return a + b\n'
    return CoderOutput(edits=[FileEdit(path="calc.py", content=f"def add(a, b):\n{body}")])


def _reviewer(name: str) -> Callable[[AgentInput], BaseModel]:
    def review(inp: AgentInput) -> BaseModel:
        wants_doc = name == "arch-reviewer" and inp.diff is not None and '"""' not in inp.diff
        findings = [Finding(severity=Severity.MAJOR, category="arch", file="calc.py", line=1,
                            issue="public function lacks a docstring", confidence=0.6)] if wants_doc else []
        return Verdict(reviewer_id=name, verdict="REQUEST_CHANGES" if findings else "APPROVE",
                       findings=findings, summary="demo")
    return review


def _project_plan(inp: AgentInput) -> ProjectPlan:
    return ProjectPlan(phases=[
        PhasePlan(title="Foundation", steps=["Fix calc.add so tests pass", "Add input validation"]),
        PhasePlan(title="Polish", steps=["Document calc module"]),
    ])


def demo_scripts() -> dict[str, Callable[[AgentInput], BaseModel]]:
    return {
        "project-planner": _project_plan,
        "planner": _plan,
        "coder": _coder,
        **{r: _reviewer(r) for r in ("correctness-reviewer", "arch-reviewer", "test-style-reviewer")},
    }
