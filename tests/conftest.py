from __future__ import annotations

from pathlib import Path

import pytest

from agentlab.core.config import AppConfig, load_config
from agentlab.core.schemas import Finding, Iteration, RunStatus, Severity, Verdict

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture(scope="session")
def cfg() -> AppConfig:
    return load_config(CONFIG_DIR)


def finding(sev: Severity = Severity.MAJOR, conf: float = 0.5, file: str = "a.py", line: int | None = 1,
            issue: str = "bug", reviewer: str = "r1", category: str = "correctness") -> Finding:
    return Finding(severity=sev, category=category, file=file, line=line, issue=issue,  # type: ignore[arg-type]
                   confidence=conf, reviewer_id=reviewer)


def verdict(reviewer: str, *findings: Finding) -> Verdict:
    return Verdict(reviewer_id=reviewer, verdict="REQUEST_CHANGES" if findings else "APPROVE",
                   findings=list(findings))


def iteration(n: int, diff_hash: str, findings: list[str] | None = None) -> Iteration:
    return Iteration(run_id="r", n=n, phase=RunStatus.GATING, diff_hash=diff_hash, finding_set=findings or [])


@pytest.fixture(autouse=True)
def no_model_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit/integration tests exercise outages without downloading GBs of model weights."""
    def unavailable(*args: object, **kwargs: object) -> None:
        raise ConnectionError("model download disabled in tests")

    monkeypatch.setattr("fastembed.TextEmbedding", unavailable)
    monkeypatch.setattr("fastembed.rerank.cross_encoder.TextCrossEncoder", unavailable)
