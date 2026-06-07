from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DocumentType(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"


class RiskDimension(str, Enum):
    FINANCIAL_SOUNDNESS = "financial_soundness"
    GOVERNANCE = "governance"
    OPERATIONAL_RESILIENCE = "operational_resilience"
    CYBERSECURITY = "cybersecurity"
    COMPLIANCE = "compliance"
    BUSINESS_MODEL = "business_model"


class AuthorizationLevel(str, Enum):
    FULL = "FULL"
    CONDITIONAL = "CONDITIONAL"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------

class DocumentRef(BaseModel):
    """A reference to a document in object storage (or locally for the demo)."""
    type: DocumentType
    path: str


class Submission(BaseModel):
    """The primary JSON file that arrives with each authorization request."""
    applicant_id: str
    firm_name: str
    declared_activities: list[str]
    documents: list[DocumentRef]


# ---------------------------------------------------------------------------
# Intermediate models (flow between pipeline stages)
# ---------------------------------------------------------------------------

class DocumentChunk(BaseModel):
    """One chunk of text extracted from a parsed document."""
    source_path: str
    page: int
    chunk_index: int
    text: str


class ExtractedSignal(BaseModel):
    """A single fact relevant to one risk dimension, pulled from a chunk."""
    dimension: RiskDimension
    fact: str
    source_path: str
    page: int


class DimensionScore(BaseModel):
    """LLM-assessed score for one risk dimension."""
    dimension: RiskDimension
    score: int = Field(ge=1, le=5)  # 1 = very high risk, 5 = very low risk
    rationale: str
    signals_used: list[ExtractedSignal]
    reviewer_override: int | None = None


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------

class FollowUpQuestion(BaseModel):
    dimension: RiskDimension
    question: str
    reason: str


class ReviewerPayload(BaseModel):
    """Final structured output delivered to the review API."""
    run_id: str
    applicant_id: str
    firm_name: str
    dimension_scores: list[DimensionScore]
    composite_score: float
    authorization_level: AuthorizationLevel
    authorization_rationale: str
    follow_up_questions: list[FollowUpQuestion]
    metadata: dict[str, Any] = Field(default_factory=dict)
