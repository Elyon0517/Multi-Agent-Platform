from __future__ import annotations

from collections import defaultdict

from agentlab.core.loop.convergence import hard_findings
from agentlab.core.schemas import (
    ArbiterAction,
    ArbiterDecision,
    Conflict,
    Finding,
    Verdict,
)


def _all_findings(verdicts: list[Verdict]) -> list[Finding]:
    return [
        f.model_copy(update={"reviewer_id": f.reviewer_id or v.reviewer_id}) for v in verdicts for f in v.findings
    ]


def dedupe_and_rank(findings: list[Finding]) -> list[Finding]:
    best: dict[str, Finding] = {}
    for f in findings:
        fp = f.fingerprint()
        if fp not in best or f.confidence > best[fp].confidence:
            best[fp] = f
    return sorted(best.values(), key=lambda f: (f.severity.rank, -f.confidence, f.file, f.line or 0))


def detect_contradictions(findings: list[Finding]) -> list[Conflict]:
    by_location: dict[tuple[str, int | None], list[Finding]] = defaultdict(list)
    for f in findings:
        by_location[(f.file, f.line)].append(f)
    conflicts = []
    for (file, line), group in by_location.items():
        reviewers_hard = {f.reviewer_id for f in group if f.severity.is_hard}
        reviewers_soft = {f.reviewer_id for f in group if not f.severity.is_hard}
        if reviewers_hard and (reviewers_soft - reviewers_hard):
            conflicts.append(Conflict(file=file, line=line, findings=group))
    return conflicts


def arbitrate(verdicts: list[Verdict], veto_confidence: float) -> ArbiterDecision:
    hard = hard_findings(verdicts)
    if not hard:
        return ArbiterDecision(action=ArbiterAction.SIGNOFF)
    ranked = dedupe_and_rank(hard)
    if any(f.confidence > veto_confidence and f.severity.rank == 0 for f in ranked):
        return ArbiterDecision(action=ArbiterAction.BACK_TO_CODER, reason="blocking_veto", instructions=ranked)
    if conflicts := detect_contradictions(_all_findings(verdicts)):
        return ArbiterDecision(action=ArbiterAction.ESCALATE, reason="reviewer_conflict", conflicts=conflicts)
    return ArbiterDecision(action=ArbiterAction.BACK_TO_CODER, reason="hard_findings", instructions=ranked)
