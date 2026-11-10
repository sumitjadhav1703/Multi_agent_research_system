"""Pydantic contracts for the evidence-first research graph."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ClaimStatus = Literal["supported", "contradictory", "insufficient"]
ApprovalStatus = Literal[
    "draft",
    "awaiting_review",
    "revision_requested",
    "approved",
    "rejected",
    "completed_unreviewed",
    "failed",
]
ExtractionMethod = Literal["html", "snippet", "unsupported_pdf", "failed"]
EVIDENCE_WORDING = "Evidence assessed against stored passages. This is not an absolute fact-check."


class SubQuestion(BaseModel):
    subquestion_id: str
    question: str
    search_query: str
    expected_evidence: str = ""
    status: Literal["pending", "inflight", "done", "skipped"] = "pending"
    kind: Literal["planned", "followup"] = "planned"
    worker_status: str | None = None


class SourceRecord(BaseModel):
    source_id: str
    url: str
    canonical_url: str
    domain: str
    title: str
    excerpt: str
    content_hash: str
    extraction_method: ExtractionMethod
    fetched: bool
    published_at: str | None = None
    retrieved_at: str
    caveats: list[str] = Field(default_factory=list)
    rank_score: float = 0
    rank_features: dict[str, float | bool] = Field(default_factory=dict)
    subquestion_id: str


class Passage(BaseModel):
    evidence_id: str
    source_id: str
    subquestion_id: str
    quote: str
    url: str
    relevance_reason: str
    term_overlap: int = 0


class Claim(BaseModel):
    claim_id: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    status: ClaimStatus = "insufficient"
    verification_reason: str


class Contradiction(BaseModel):
    contradiction_id: str
    claim_id: str
    summary: str
    evidence_ids: list[str] = Field(default_factory=list)


class ReportSection(BaseModel):
    section_id: str
    heading: str
    body: str
    evidence_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    kind: Literal["finding", "conflict", "gap", "caveat"] = "finding"


class ReportDraft(BaseModel):
    title: str
    sections: list[ReportSection] = Field(default_factory=list)
    wording: str = EVIDENCE_WORDING


class CitationIssue(BaseModel):
    code: str
    detail: str


class ReviewDecision(BaseModel):
    action: Literal["approve", "revise", "reject"]
    comments: str = ""

    @field_validator("comments")
    @classmethod
    def _cap_comments(cls, value: str) -> str:
        return value.strip()[:2000]


class SearchHit(BaseModel):
    title: str
    url: str
    snippet: str = ""


class FetchResult(BaseModel):
    url: str
    text: str = ""
    extraction_method: ExtractionMethod = "failed"
    caveat: str | None = None


class WorkerResult(BaseModel):
    result_id: str
    subquestion_id: str
    status: Literal["ok", "partial", "failed"]
    search_query: str
    search_calls: int = 0
    sources: list[SourceRecord] = Field(default_factory=list)
    passages: list[Passage] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
