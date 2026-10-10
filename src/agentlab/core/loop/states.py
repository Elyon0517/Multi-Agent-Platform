from __future__ import annotations

from agentlab.core.schemas import RunStatus as S


class IllegalTransition(RuntimeError):
    pass


ACTIVE = frozenset({S.PLANNING, S.CODING, S.GATING, S.REVIEWING, S.ARBITRATING})
TERMINAL = frozenset({S.DONE, S.CANCELLED})

TRANSITIONS: dict[S, frozenset[S]] = {
    S.PLANNING: frozenset({S.CODING}),
    S.CODING: frozenset({S.GATING}),
    S.GATING: frozenset({S.REVIEWING, S.CODING}),
    S.REVIEWING: frozenset({S.ARBITRATING}),
    S.ARBITRATING: frozenset({S.CODING, S.WAITING_HUMAN}),
    S.WAITING_HUMAN: frozenset({S.DONE, S.CANCELLED} | ACTIVE),
    S.DONE: frozenset(),
    S.CANCELLED: frozenset(),
}


def can_transition(src: S, dst: S) -> bool:
    if src in ACTIVE and dst in (S.WAITING_HUMAN, S.CANCELLED):
        return True
    return dst in TRANSITIONS[src]


def check_transition(src: S, dst: S) -> None:
    if not can_transition(src, dst):
        raise IllegalTransition(f"{src} -> {dst}")
