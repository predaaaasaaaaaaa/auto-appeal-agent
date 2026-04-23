"""
Structured I/O schemas for every pipeline stage.

Reliability contract:
- Every LLM output is parsed through Pydantic (`model_validate_json`). A
  malformed or extra-field response raises instead of silently corrupting state.
- Every factual claim in the final appeal is a `CitationMarker` pointing by
  `source_id` at a `SourceQuote` captured upstream. The Verifier uses these
  pointers to re-check every claim against the original document.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

SourceType = Literal[
    "denial_letter",
    "patient_chart",
    "payer_policy",
    "clinical_guideline",
]

EvidenceCategory = Literal[
    "clinical_history",
    "diagnostics",
    "prior_treatments",
    "functional_status",
    "contraindications",
    "other",
]


class Strict(BaseModel):
    """Base model: reject unknown fields; validate on assignment."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SourceQuote(Strict):
    quote_id: str = Field(..., description="Stable ID, e.g. 'denial_q1', 'chart_q3'.")
    source_type: SourceType
    quote: str = Field(..., description="Verbatim text copied from the source document.")
    location: str = Field(
        ...,
        description="Human-readable location, e.g. 'page 1, paragraph 2' or '2026-03-12 progress note'.",
    )


class CitationMarker(Strict):
    claim: str = Field(..., description="The factual claim being made in the appeal.")
    source_type: SourceType
    source_id: str = Field(..., description="FK to SourceQuote.quote_id.")
    verbatim_quote: str = Field(
        ...,
        description="Exact substring the Verifier will search for in the source text.",
    )


class PipelineInput(Strict):
    case_id: str
    denial_letter_path: str
    patient_chart_path: str
    payer_policy_path: str


class MemberInfo(Strict):
    member_name: str
    member_id: str
    date_of_birth: Optional[str] = None
    plan_name: str


class DenialReason(Strict):
    reason: str = Field(..., description="Plain-language denial reason.")
    code: Optional[str] = None
    quote: str
    quote_location: str


class DenialAnalysis(Strict):
    case_id: str
    member_info: MemberInfo
    requested_service: str
    denial_date: Optional[str] = None
    denial_reasons: list[DenialReason]
    source_quotes: list[SourceQuote]


class MedicalNecessityCriterion(Strict):
    criterion_id: str = Field(..., description="Stable ID, e.g. 'mn_1'.")
    text: str = Field(..., description="Plain-language criterion.")
    quote: str
    quote_location: str
    category: EvidenceCategory


class PolicyCriteria(Strict):
    case_id: str
    policy_name: str
    policy_effective_date: Optional[str] = None
    criteria: list[MedicalNecessityCriterion]
    source_quotes: list[SourceQuote]


class EvidenceItem(Strict):
    criterion_id: str = Field(..., description="FK to MedicalNecessityCriterion.criterion_id.")
    finding: str
    quote: str
    quote_location: str
    supports_appeal: bool


class ChartEvidence(Strict):
    case_id: str
    evidence_items: list[EvidenceItem]
    criteria_met: dict[str, bool] = Field(
        default_factory=dict,
        description="Map of criterion_id -> True if sufficient evidence supports appeal.",
    )
    source_quotes: list[SourceQuote]


class GuidelineCitation(Strict):
    citation_id: str
    guideline_source: str = Field(
        ..., description="Issuing body, e.g. 'ADA 2024 Standards of Care'."
    )
    # Optional: not every guideline has a clean section title Claude can
    # confidently name. The appeal still reads fine when this is missing.
    citation_title: Optional[str] = None
    quote: str
    url: Optional[str] = None
    supports_claim: str = Field(..., description="What clinical claim this citation backs.")


class GuidelineCitations(Strict):
    case_id: str
    citations: list[GuidelineCitation]


class AppealParagraph(Strict):
    heading: Optional[str] = None
    text: str
    citations: list[CitationMarker]


class AppealDraft(Strict):
    case_id: str
    recipient_plan: str
    subject_line: str
    paragraphs: list[AppealParagraph]


class VerifiedCitation(Strict):
    citation: CitationMarker
    verified: bool
    verification_method: Literal["exact_substring", "normalized_substring", "manual"] = (
        "exact_substring"
    )
    notes: str = ""


class RejectedCitation(Strict):
    citation: CitationMarker
    rejection_reason: str


class CitationVerdict(Strict):
    """Independent-reviewer verdict for one citation in the draft."""

    paragraph_index: int = Field(..., ge=0)
    citation_in_paragraph_index: int = Field(..., ge=0)
    source_id: str
    verdict: Literal["supports", "partial", "unsupported"]
    rationale: str = Field(..., description="One-sentence explanation.")


class AppealReview(Strict):
    """Output of the independent (second-pass) reviewer.

    Ran after the substring Verifier passes; gives a fresh, prompt-isolated
    second opinion on whether each citation actually supports the claim.
    """

    case_id: str
    overall_verdict: Literal["sign_ready", "needs_revision"]
    citation_verdicts: list[CitationVerdict]
    high_level_concerns: list[str] = Field(
        default_factory=list,
        description="Issues spanning the letter (tone, missing arguments, etc.).",
    )
    reviewer_summary: str = Field(
        ..., description="One-paragraph summary of the review."
    )


class VerifiedAppeal(Strict):
    case_id: str
    draft: AppealDraft
    verified_citations: list[VerifiedCitation]
    rejected_citations: list[RejectedCitation]
    verification_pass_rate: float = Field(..., ge=0.0, le=1.0)
    ready_to_send: bool = Field(
        ...,
        description="True only when verification_pass_rate == 1.0 and no rejected citations.",
    )
    second_pass_review: Optional[AppealReview] = Field(
        default=None,
        description=(
            "Independent-reviewer verdict, populated when the orchestrator "
            "is invoked with second_pass=True."
        ),
    )
