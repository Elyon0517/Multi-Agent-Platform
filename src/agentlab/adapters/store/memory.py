from __future__ import annotations

import threading
from collections import defaultdict

from agentlab.core.schemas import (
    Approval,
    ApprovalStatus,
    Artifact,
    ArtifactKind,
    Event,
    Iteration,
    Run,
    Step,
)


class NotFound(KeyError):
    pass


class InMemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, Run] = {}
        self._iterations: dict[str, list[Iteration]] = defaultdict(list)
        self._steps: dict[str, list[Step]] = defaultdict(list)
        self._artifacts: dict[str, list[Artifact]] = defaultdict(list)
        self._approvals: dict[str, list[Approval]] = defaultdict(list)
        self._events: dict[str, list[Event]] = defaultdict(list)

    def create_run(self, run: Run) -> Run:
        with self._lock:
            self._runs[run.id] = run.model_copy(deep=True)
        return run

    def get_run(self, run_id: str) -> Run:
        try:
            return self._runs[run_id].model_copy(deep=True)
        except KeyError as e:
            raise NotFound(run_id) from e

    def save_run(self, run: Run) -> None:
        with self._lock:
            self._runs[run.id] = run.model_copy(deep=True)

    def list_runs(self) -> list[Run]:
        return sorted((r.model_copy() for r in self._runs.values()), key=lambda r: r.created_at, reverse=True)

    def add_iteration(self, it: Iteration) -> None:
        with self._lock:
            self._iterations[it.run_id].append(it.model_copy(deep=True))

    def save_iteration(self, it: Iteration) -> None:
        with self._lock:
            items = self._iterations[it.run_id]
            items[next(i for i, x in enumerate(items) if x.id == it.id)] = it.model_copy(deep=True)

    def iterations(self, run_id: str) -> list[Iteration]:
        return [i.model_copy(deep=True) for i in self._iterations[run_id]]

    def add_step(self, step: Step) -> None:
        with self._lock:
            self._steps[step.run_id].append(step)

    def steps(self, run_id: str) -> list[Step]:
        return list(self._steps[run_id])

    def add_artifact(self, artifact: Artifact) -> None:
        with self._lock:
            self._artifacts[artifact.run_id].append(artifact)

    def artifacts(self, run_id: str, kind: ArtifactKind | None = None) -> list[Artifact]:
        return [a for a in self._artifacts[run_id] if kind is None or a.kind == kind]

    def create_approval(self, approval: Approval) -> None:
        with self._lock:
            self._approvals[approval.run_id].append(approval.model_copy())

    def pending_approval(self, run_id: str) -> Approval | None:
        pending = [a for a in self._approvals[run_id] if a.status == ApprovalStatus.PENDING]
        return pending[-1].model_copy() if pending else None

    def save_approval(self, approval: Approval) -> None:
        with self._lock:
            items = self._approvals[approval.run_id]
            items[next(i for i, x in enumerate(items) if x.id == approval.id)] = approval.model_copy()

    def append_event(self, event: Event) -> Event:
        with self._lock:
            stored = event.model_copy(update={"seq": len(self._events[event.run_id]) + 1})
            self._events[event.run_id].append(stored)
        return stored

    def events(self, run_id: str, after_seq: int = 0) -> list[Event]:
        return [e for e in self._events[run_id] if e.seq > after_seq]
