from __future__ import annotations

import hashlib

from agentlab.core.schemas import Finding, GateResult, Iteration, Verdict, normalize_text


def all_signoff(verdicts: list[Verdict]) -> bool:
    return bool(verdicts) and all(v.is_signoff for v in verdicts)


def hard_findings(verdicts: list[Verdict]) -> list[Finding]:
    return [
        f.model_copy(update={"reviewer_id": f.reviewer_id or v.reviewer_id})
        for v in verdicts
        for f in v.findings
        if f.severity.is_hard
    ]


def review_fingerprints(verdicts: list[Verdict]) -> list[str]:
    return sorted({f.fingerprint() for f in hard_findings(verdicts)})


def gate_fingerprints(gate: GateResult) -> list[str]:
    keys = {
        f"{s.name}|{d.file}|{d.code}|{normalize_text(d.message)}"
        for s in gate.steps
        if not s.passed
        for d in s.diagnostics
    } or {f"{s.name}|exit={s.exit_code}" for s in gate.steps if not s.passed}
    return sorted(hashlib.sha256(k.encode()).hexdigest()[:16] for k in keys)


def is_oscillating(history: list[Iteration]) -> bool:
    if len(history) < 2:
        return False
    a, b = history[-1], history[-2]
    if a.diff_hash == b.diff_hash:
        return True
    return bool(a.finding_set) and a.finding_set == b.finding_set
