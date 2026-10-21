from __future__ import annotations

import pytest

from agentlab.core.loop.arbiter import arbitrate, dedupe_and_rank, detect_contradictions
from agentlab.core.loop.convergence import all_signoff, is_oscillating, review_fingerprints
from agentlab.core.loop.states import IllegalTransition, can_transition, check_transition
from agentlab.core.schemas import ArbiterAction, Severity
from agentlab.core.schemas import RunStatus as S
from tests.conftest import finding, iteration, verdict


class TestStates:
    @pytest.mark.parametrize("src,dst", [
        (S.PLANNING, S.CODING), (S.CODING, S.REVIEWING), (S.CODING, S.GATING), (S.GATING, S.REVIEWING), (S.GATING, S.CODING),
        (S.REVIEWING, S.ARBITRATING), (S.ARBITRATING, S.CODING), (S.ARBITRATING, S.WAITING_HUMAN),
        (S.WAITING_HUMAN, S.DONE), (S.WAITING_HUMAN, S.CODING), (S.WAITING_HUMAN, S.CANCELLED),
        (S.CODING, S.WAITING_HUMAN), (S.REVIEWING, S.CANCELLED), (S.DONE, S.CODING), (S.CODING, S.DONE),
    ])
    def test_legal(self, src: S, dst: S) -> None:
        assert can_transition(src, dst)

    @pytest.mark.parametrize("src,dst", [
        (S.PLANNING, S.REVIEWING), (S.GATING, S.DONE),
        (S.CANCELLED, S.PLANNING), (S.REVIEWING, S.DONE),
    ])
    def test_illegal(self, src: S, dst: S) -> None:
        with pytest.raises(IllegalTransition):
            check_transition(src, dst)


class TestConvergence:
    def test_minor_and_nit_do_not_block(self) -> None:
        v = verdict("r1", finding(Severity.MINOR), finding(Severity.NIT))
        assert v.is_signoff and all_signoff([v])

    def test_major_blocks(self) -> None:
        assert not all_signoff([verdict("r1"), verdict("r2", finding(Severity.MAJOR))])

    def test_no_verdicts_is_not_signoff(self) -> None:
        assert not all_signoff([])

    def test_fingerprint_ignores_whitespace_and_punctuation(self) -> None:
        a = finding(issue="Missing  null check!")
        b = finding(issue="missing null check", reviewer="r2", conf=0.9)
        assert a.fingerprint() == b.fingerprint()

    def test_review_fingerprints_only_hard(self) -> None:
        fps = review_fingerprints([verdict("r1", finding(Severity.MAJOR), finding(Severity.NIT, issue="x"))])
        assert len(fps) == 1


class TestOscillation:
    def test_needs_two_iterations(self) -> None:
        assert not is_oscillating([iteration(1, "a")])

    def test_same_diff(self) -> None:
        assert is_oscillating([iteration(1, "a"), iteration(2, "a")])

    def test_same_findings(self) -> None:
        assert is_oscillating([iteration(1, "a", ["f1"]), iteration(2, "b", ["f1"])])

    def test_progress(self) -> None:
        assert not is_oscillating([iteration(1, "a", ["f1"]), iteration(2, "b", ["f2"])])

    def test_empty_findings_not_oscillating(self) -> None:
        assert not is_oscillating([iteration(1, "a"), iteration(2, "b")])


class TestArbiter:
    def test_signoff_when_no_hard(self) -> None:
        d = arbitrate([verdict("r1", finding(Severity.NIT)), verdict("r2")], 0.7)
        assert d.action == ArbiterAction.SIGNOFF

    def test_high_confidence_blocking_vetoes_even_with_conflict(self) -> None:
        d = arbitrate([
            verdict("r1", finding(Severity.BLOCKING, conf=0.9)),
            verdict("r2", finding(Severity.NIT, reviewer="r2")),
        ], 0.7)
        assert d.action == ArbiterAction.BACK_TO_CODER and d.reason == "blocking_veto"

    def test_conflict_escalates(self) -> None:
        d = arbitrate([
            verdict("r1", finding(Severity.MAJOR, conf=0.6, issue="must lock").model_copy(update={"subject": "add-lock", "stance": "require"})),
            verdict("r2", finding(Severity.MAJOR, conf=0.6, issue="lock is harmful", reviewer="r2").model_copy(update={"subject": "add-lock", "stance": "forbid"})),
        ], 0.7)
        assert d.action == ArbiterAction.ESCALATE and d.conflicts

    def test_low_confidence_blocking_is_not_ignored(self) -> None:
        d = arbitrate([verdict("r1", finding(Severity.BLOCKING, conf=0.2))], 0.7)
        assert d.action == ArbiterAction.BACK_TO_CODER and d.instructions[0].severity == Severity.BLOCKING

    def test_dedupe_keeps_highest_confidence_and_ranks(self) -> None:
        ranked = dedupe_and_rank([
            finding(Severity.MAJOR, conf=0.4), finding(Severity.MAJOR, conf=0.8, reviewer="r2"),
            finding(Severity.BLOCKING, conf=0.3, issue="other"),
        ])
        assert [f.severity for f in ranked] == [Severity.BLOCKING, Severity.MAJOR]
        assert ranked[1].confidence == 0.8

    def test_same_reviewer_mixed_severity_is_not_conflict(self) -> None:
        assert not detect_contradictions([finding(Severity.MAJOR), finding(Severity.NIT, issue="y")])
