from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel

from agentlab.core.schemas import (
    AgentInput,
    AgentResult,
    Approval,
    Artifact,
    ArtifactKind,
    Event,
    FileEdit,
    GateMode,
    GateResult,
    Iteration,
    Run,
    Step,
    Usage,
)

T = TypeVar("T", bound=BaseModel)


class BudgetCheck(Protocol):
    def __call__(self, estimate_cents: float) -> None: ...


@dataclass(frozen=True)
class RunContext:
    run: Run
    check_budget: BudgetCheck
    record_usage: Callable[[Usage], None] | None = None
    reserve_budget: Callable[[float], None] | None = None
    release_budget: Callable[[float], None] | None = None


class AgentRuntime(Protocol):
    async def run_agent(
        self, role: str, inp: AgentInput, output_type: type[T], ctx: RunContext
    ) -> AgentResult[T]: ...

    async def run_parallel(
        self, inputs: dict[str, AgentInput], output_type: type[T], ctx: RunContext
    ) -> list[AgentResult[T]]: ...


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False


class Sandbox(Protocol):
    async def exec(
        self,
        argv: list[str],
        cwd: Path,
        timeout_s: float,
        image: str | None = None,
        network: bool = False,
    ) -> ExecResult: ...


class Workspace(Protocol):
    root: Path

    def begin_run(self) -> None: ...

    def read(self, path: str) -> str: ...

    async def context_files(self) -> dict[str, str]: ...

    def apply_edits(self, edits: list[FileEdit]) -> list[str]: ...

    async def diff(self) -> str: ...


class GateAdapter(Protocol):
    language: str

    def detect(self, workspace: Path) -> bool: ...

    async def run(self, workspace: Path, mode: GateMode) -> GateResult: ...


class BlobStore(Protocol):
    def put(self, content: str) -> tuple[str, str]: ...

    def get(self, ref: str) -> str: ...


class Store(Protocol):
    def create_run(self, run: Run) -> Run: ...

    def get_run(self, run_id: str) -> Run: ...

    def save_run(self, run: Run) -> None: ...

    def list_runs(self) -> list[Run]: ...

    def add_iteration(self, it: Iteration) -> None: ...

    def save_iteration(self, it: Iteration) -> None: ...

    def iterations(self, run_id: str) -> list[Iteration]: ...

    def add_step(self, step: Step) -> None: ...

    def steps(self, run_id: str) -> list[Step]: ...

    def add_artifact(self, artifact: Artifact) -> None: ...

    def artifacts(self, run_id: str, kind: ArtifactKind | None = None) -> list[Artifact]: ...

    def create_approval(self, approval: Approval) -> None: ...

    def pending_approval(self, run_id: str) -> Approval | None: ...

    def save_approval(self, approval: Approval) -> None: ...

    def append_event(self, event: Event) -> Event: ...

    def events(self, run_id: str, after_seq: int = 0) -> list[Event]: ...


class EventBus(Protocol):
    def publish(self, event: Event) -> None: ...

    def subscribe(self, run_id: str) -> AsyncIterator[Event]: ...


class MemoryStore(Protocol):
    def add(self, project_id: str, namespace: str, kind: str, text: str, source_run_id: str) -> str: ...

    def search(self, project_id: str, namespaces: list[str], query: str, k: int = 8) -> list[str]: ...


class Blackboard(Protocol):
    def get(self, project_id: str, key: str) -> tuple[object, int] | None: ...

    def put(self, project_id: str, key: str, value: object, expected_version: int, by: str) -> int: ...
