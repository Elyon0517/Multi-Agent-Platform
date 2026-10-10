from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Generic, Literal, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator


def new_id() -> str:
    return uuid4().hex[:12]


def utcnow() -> datetime:
    return datetime.now(UTC)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class Severity(StrEnum):
    BLOCKING = "blocking"
    MAJOR = "major"
    MINOR = "minor"
    NIT = "nit"

    @property
    def is_hard(self) -> bool:
        return self in (Severity.BLOCKING, Severity.MAJOR)

    @property
    def rank(self) -> int:
        return list(Severity).index(self)


Category = Literal["correctness", "security", "perf", "style", "test", "arch"]


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.lower())).strip()


class Finding(Strict):
    severity: Severity
    category: Category
    file: str
    line: int | None = None
    issue: str
    suggestion: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    reviewer_id: str = ""
    subject: Literal[
        "",
        "add-validation",
        "remove-validation",
        "add-lock",
        "remove-lock",
        "change-interface",
        "preserve-interface",
        "add-test",
        "remove-test",
        "change-algorithm",
        "preserve-algorithm",
    ] = ""
    stance: Literal["require", "forbid"] | None = None

    @field_validator("subject", mode="before")
    @classmethod
    def normalize_subject(cls, value: object) -> str:
        allowed = {
            "",
            "add-validation",
            "remove-validation",
            "add-lock",
            "remove-lock",
            "change-interface",
            "preserve-interface",
            "add-test",
            "remove-test",
            "change-algorithm",
            "preserve-algorithm",
        }
        normalized = value.strip().casefold() if isinstance(value, str) else ""
        if normalized not in allowed or not isinstance(value, str):
            logging.getLogger(__name__).warning("unknown finding subject normalized to empty")
            return ""
        return normalized

    def fingerprint(self) -> str:
        key = f"{self.file}|{self.category}|{self.severity}|{normalize_text(self.issue)}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]


class Verdict(Strict):
    reviewer_id: str
    verdict: Literal["APPROVE", "REQUEST_CHANGES", "BLOCK"]
    findings: list[Finding] = []
    summary: str = ""

    @property
    def is_signoff(self) -> bool:
        return self.verdict != "BLOCK" and not any(f.severity.is_hard for f in self.findings)


class Plan(Strict):
    summary: str
    steps: list[str]
    acceptance_criteria: list[str]


class FileEdit(Strict):
    path: str
    content: str


class CoderOutput(Strict):
    edits: list[FileEdit]


class MemoryNote(Strict):
    text: str
    namespace: str = "shared"


class SummaryOutput(Strict):
    notes: list[MemoryNote]


class Diagnostic(Strict):
    file: str
    line: int | None = None
    col: int | None = None
    code: str = ""
    message: str


class GateMode(StrEnum):
    FAST = "fast"
    FULL = "full"


class GateStepResult(Strict):
    name: str
    passed: bool
    exit_code: int
    duration_ms: int
    diagnostics: list[Diagnostic] = []
    log_tail: str = ""
    truncated_log_ref: str | None = None


class GateResult(Strict):
    language: str
    mode: GateMode
    passed: bool
    steps: list[GateStepResult]
    failed_at: str | None = None


class ArbiterAction(StrEnum):
    SIGNOFF = "SIGNOFF"
    ESCALATE = "ESCALATE"
    BACK_TO_CODER = "BACK_TO_CODER"


class Conflict(Strict):
    file: str
    line: int | None
    findings: list[Finding]


class ArbiterDecision(Strict):
    action: ArbiterAction
    reason: str = ""
    instructions: list[Finding] = []
    conflicts: list[Conflict] = []


class RunStatus(StrEnum):
    PLANNING = "PLANNING"
    CODING = "CODING"
    GATING = "GATING"
    REVIEWING = "REVIEWING"
    ARBITRATING = "ARBITRATING"
    WAITING_HUMAN = "WAITING_HUMAN"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class Run(Strict):
    thread_id: str | None = None
    id: str = Field(default_factory=new_id)
    project_id: str = "default"
    goal: str
    workspace: str
    language: str | None = None
    policy: str = "auto"
    status: RunStatus = RunStatus.PLANNING
    max_iter: int = 5
    iteration_base: int = 0
    budget_cents: float = 500.0
    cost_cents: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    paused_reason: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Iteration(Strict):
    id: str = Field(default_factory=new_id)
    run_id: str
    n: int
    phase: RunStatus
    diff_hash: str
    gate_result: GateResult | None = None
    verdicts: list[Verdict] = []
    finding_set: list[str] = []


class Usage(Strict):
    tokens_in: int = 0
    tokens_out: int = 0
    cost_cents: float = 0.0
    _call: dict[str, Any] | None = PrivateAttr(default=None)

    def for_call(
        self, role: str, model_alias: str, model: str, call_id: str | None = None, metered: bool = True,
    ) -> Usage:
        usage = self.model_copy()
        usage._call = {"role": role, "model_alias": model_alias, "model": model,
                       "id": "call-" + (call_id or new_id()), "metered": metered}
        return usage


class Step(Strict):
    id: str = Field(default_factory=new_id)
    run_id: str
    iteration_n: int
    role: str
    model_alias: str
    model: str
    usage: Usage = Usage()
    latency_ms: int = 0
    attempt_count: int = 1
    retry_reasons: list[str] = []
    routing_reason: str = ""
    parent_step_id: str | None = None
    prompt_ref: str | None = None
    response_ref: str | None = None


ArtifactKind = Literal["dispatch", "plan", "diff", "review", "gate", "arbiter", "feedback", "memory"]


class Artifact(Strict):
    id: str = Field(default_factory=new_id)
    run_id: str
    kind: ArtifactKind
    sha256: str
    content_ref: str
    created_by_step: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ABORTED = "aborted"


class SignoffReport(Strict):
    goal: str
    acceptance_criteria: list[str]
    automated_checks: Literal["passed", "not_run"]
    findings: list[Finding]


class Approval(Strict):
    id: str = Field(default_factory=new_id)
    run_id: str
    reason: str
    on_approve: RunStatus = RunStatus.CODING
    payload: dict[str, Any] = {}
    report: SignoffReport | None = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    decided_by: str | None = None
    feedback: str | None = None
    decided_at: datetime | None = None


class EventType(StrEnum):
    MESSAGE_CREATED = "message.created"
    MESSAGE_DELTA = "message.delta"
    TURN_FINISHED = "turn.finished"
    RUN_CREATED = "run.created"
    RUN_STATUS = "run.status"
    STEP_STARTED = "step.started"
    STEP_TOOL_CALL = "step.tool_call"
    STEP_FINISHED = "step.finished"
    ARTIFACT_CREATED = "artifact.created"
    GATE_FINISHED = "gate.finished"
    ARBITER_DECISION = "arbiter.decision"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_DECIDED = "approval.decided"
    BUDGET_WARNING = "budget.warning"


class Event(Strict):
    run_id: str
    seq: int = 0
    ts: datetime = Field(default_factory=utcnow)
    type: EventType
    actor: str = "driver"
    payload: dict[str, Any] = {}


class AgentInput(Strict):
    run_id: str
    iteration: int
    goal: str
    plan: Plan | None = None
    diff: str | None = None
    gate: GateResult | None = None
    instructions: list[Finding] = []
    feedback: str | None = None
    context: dict[str, Any] = {}


T = TypeVar("T", bound=BaseModel)


class AgentResult(BaseModel, Generic[T]):
    role: str
    output: T
    alias: str
    model: str
    usage: Usage = Usage()
    latency_ms: int = 0
    attempts: int = 1
    retry_reasons: list[str] = []
    routing_reason: str = ""
    usage_recorded: bool = False
    prompt_ref: str | None = None
    response_ref: str | None = None
