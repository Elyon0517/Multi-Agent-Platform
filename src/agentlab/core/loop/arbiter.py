from __future__ import annotations

from collections import defaultdict

from agentlab.core.schemas import (
    ArbiterAction,
    ArbiterDecision,
    Conflict,
    Finding,
    Verdict,
)


def _all_findings(verdicts: list[Verdict]) -> list[Finding]:
    return [
        f.model_copy(update={"reviewer_id": v.reviewer_id}) for v in verdicts for f in v.findings
    ]


def dedupe_and_rank(findings: list[Finding]) -> list[Finding]:
    best: dict[str, Finding] = {}
    for f in findings:
        fp = f.fingerprint()
        if fp not in best or f.confidence > best[fp].confidence:
            best[fp] = f
    return sorted(best.values(), key=lambda f: (f.severity.rank, -f.confidence, f.file, f.line or 0))


def detect_contradictions(findings: list[Finding]) -> list[Conflict]:
    # Only opposing, explicitly identified requirements constitute a contradiction.
    groups: dict[tuple[str, str], list[Finding]] = defaultdict(list)
    inverses = {"remove-validation": "add-validation", "remove-lock": "add-lock",
                "preserve-interface": "change-interface", "remove-test": "add-test",
                "preserve-algorithm": "change-algorithm"}
    for finding in findings:
        if finding.severity.is_hard and finding.subject and finding.stance:
            subject = finding.subject
            if subject in inverses:
                finding = finding.model_copy(update={
                    "subject": inverses[subject],
                    "stance": "forbid" if finding.stance == "require" else "require",
                })
            groups[(finding.file, finding.subject)].append(finding)
    conflicts = []
    for (file, _), group in groups.items():
        if any(a.reviewer_id != b.reviewer_id and a.stance != b.stance for a in group for b in group):
            conflicts.append(Conflict(file=file, line=None, findings=group))
    return conflicts


def arbitrate(verdicts: list[Verdict], veto_confidence: float) -> ArbiterDecision:
    hard = [finding for finding in _all_findings(verdicts) if finding.severity.is_hard]
    ranked = dedupe_and_rank(hard)
    if any(f.confidence > veto_confidence and f.severity.rank == 0 for f in ranked):
        return ArbiterDecision(action=ArbiterAction.BACK_TO_CODER, reason="blocking_veto", instructions=ranked)
    if not verdicts or any(v.verdict == "BLOCK" and not any(f.severity.is_hard for f in v.findings)
                           for v in verdicts):
        return ArbiterDecision(action=ArbiterAction.ESCALATE, reason="inconsistent_verdict")
    if conflicts := detect_contradictions(hard):
        return ArbiterDecision(action=ArbiterAction.ESCALATE, reason="reviewer_conflict", conflicts=conflicts)
    if not hard:
        return ArbiterDecision(action=ArbiterAction.SIGNOFF)
    return ArbiterDecision(action=ArbiterAction.BACK_TO_CODER, reason="hard_findings", instructions=ranked)
