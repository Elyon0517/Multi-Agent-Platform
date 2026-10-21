"""Task-specific evidence contracts: mechanical coverage, never semantic approval."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import Field, model_validator

from agentlab.core.schemas import Strict


class EvidenceRequirement(Strict):
    id: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1500)
    claim_path: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered(self) -> EvidenceRequirement:
        if self.line_end < self.line_start:
            raise ValueError("invalid claim range")
        return self


class EvidenceContract(Strict):
    requirements: list[EvidenceRequirement] = Field(min_length=1, max_length=500)
    source_paths: list[str] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_ids(self) -> EvidenceContract:
        if len({r.id for r in self.requirements}) != len(self.requirements):
            raise ValueError("duplicate evidence requirement id")
        return self


class Citation(Strict):
    path: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    quote: str = Field(min_length=8, max_length=2000)


class EvidenceRecord(Strict):
    id: str
    claim: Citation
    sources: list[Citation] = Field(min_length=1, max_length=12)
    verdict: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=10, max_length=5000)
    calculation: str = Field(max_length=2000)
    # A negative claim requires actual scoped searches, not a fabricated search narrative.
    negative_claim: bool
    searches: list[dict[str, str]] = Field(max_length=30)


def validate_record(record: EvidenceRecord, contract: EvidenceContract,
                    reader: Callable[[str], str], searches: list[dict[str, str]]) -> None:
    requirement = next((r for r in contract.requirements if r.id == record.id), None)
    if requirement is None:
        raise ValueError("unknown evidence id")
    claim = record.claim
    if (claim.path != requirement.claim_path or claim.line_start < requirement.line_start
            or claim.line_end > requirement.line_end):
        raise ValueError("claim citation outside required item")
    for citation in [claim, *record.sources]:
        if citation is not claim and citation.path not in contract.source_paths:
            raise ValueError("source citation not in evidence contract")
        lines = reader(citation.path).splitlines(keepends=True)
        if citation.line_end < citation.line_start or citation.line_end > len(lines):
            raise ValueError("citation outside source")
        if citation.line_end - citation.line_start > 30:
            raise ValueError("cite a precise range of at most 31 lines")
        if citation.quote not in "".join(lines[citation.line_start - 1:citation.line_end]):
            raise ValueError(f"quote does not match {citation.path}:{citation.line_start}-{citation.line_end}")
    if record.negative_claim and not record.searches:
        raise ValueError("negative claim requires executed scoped searches")
    for search in record.searches:
        if set(search) != {"path", "query"} or not search["query"].strip():
            raise ValueError("search reference requires exact path and nonempty query")
        if search["path"] not in contract.source_paths or search not in searches:
            raise ValueError("search was not executed against a contract source")


def evidence_status(state: dict[str, Any]) -> dict[str, Any]:
    contract = EvidenceContract.model_validate(state["contract"])
    rows = state.get("records", {})
    missing = [r.model_dump() for r in contract.requirements if r.id not in rows]
    return {"required_count": len(contract.requirements), "recorded_count": len(rows),
            "missing_count": len(missing), "next_requirements": missing[:8],
            "meaning": "Quote/coverage checks only; semantic signoff is still required."}
