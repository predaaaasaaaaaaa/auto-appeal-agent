"""
Schema validation tests.

These don't call any LLM — they verify that our Pydantic models correctly:
  (a) accept well-formed objects,
  (b) reject malformed/extra-field objects,
  (c) round-trip cleanly through JSON.

If any of these fail, no downstream stage is trustworthy.
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from auto_appeal_agent.schemas import (
    AppealDraft,
    AppealParagraph,
    ChartEvidence,
    CitationMarker,
    DenialAnalysis,
    DenialReason,
    EvidenceItem,
    GuidelineCitation,
    GuidelineCitations,
    MedicalNecessityCriterion,
    MemberInfo,
    PipelineInput,
    PolicyCriteria,
    RejectedCitation,
    SourceQuote,
    VerifiedAppeal,
    VerifiedCitation,
)


def test_source_quote_roundtrip():
    sq = SourceQuote(
        quote_id="denial_q1",
        source_type="denial_letter",
        quote="The requested service is not medically necessary.",
        location="page 1, paragraph 2",
    )
    restored = SourceQuote.model_validate_json(sq.model_dump_json())
    assert restored == sq


def test_strict_rejects_extra_fields():
    with pytest.raises(ValidationError):
        SourceQuote.model_validate(
            {
                "quote_id": "x",
                "source_type": "denial_letter",
                "quote": "y",
                "location": "z",
                "hallucinated_extra_field": "nope",
            }
        )


def test_citation_marker_valid_source_type():
    cm = CitationMarker(
        claim="BMI is 34.2.",
        source_type="patient_chart",
        source_id="chart_q7",
        verbatim_quote="BMI 34.2",
    )
    assert cm.source_type == "patient_chart"


def test_citation_marker_invalid_source_type():
    with pytest.raises(ValidationError):
        CitationMarker.model_validate(
            {
                "claim": "x",
                "source_type": "wikipedia",
                "source_id": "q1",
                "verbatim_quote": "y",
            }
        )


def test_verified_appeal_pass_rate_bounds():
    # 0.0 ok
    VerifiedAppeal(
        case_id="c1",
        draft=AppealDraft(
            case_id="c1",
            recipient_plan="ACME Health",
            subject_line="Appeal",
            paragraphs=[],
        ),
        verified_citations=[],
        rejected_citations=[],
        verification_pass_rate=0.0,
        ready_to_send=False,
    )
    # >1.0 rejected
    with pytest.raises(ValidationError):
        VerifiedAppeal(
            case_id="c1",
            draft=AppealDraft(
                case_id="c1",
                recipient_plan="ACME Health",
                subject_line="Appeal",
                paragraphs=[],
            ),
            verified_citations=[],
            rejected_citations=[],
            verification_pass_rate=1.5,
            ready_to_send=True,
        )


def test_full_pipeline_shape_compiles():
    """Sanity: every pipeline stage's output can be constructed with minimal data."""
    case_id = "case_smoke"
    denial = DenialAnalysis(
        case_id=case_id,
        member_info=MemberInfo(
            member_name="Jane Doe", member_id="A12345", plan_name="ACME Health"
        ),
        requested_service="Ozempic 1mg weekly",
        denial_reasons=[
            DenialReason(
                reason="Not medically necessary",
                code="MN-12",
                quote="not medically necessary",
                quote_location="page 1",
            )
        ],
        source_quotes=[
            SourceQuote(
                quote_id="denial_q1",
                source_type="denial_letter",
                quote="not medically necessary",
                location="page 1",
            )
        ],
    )
    policy = PolicyCriteria(
        case_id=case_id,
        policy_name="ACME GLP-1 Policy v3",
        criteria=[
            MedicalNecessityCriterion(
                criterion_id="mn_1",
                text="BMI >= 30",
                quote="BMI greater than or equal to 30",
                quote_location="section 2",
                category="diagnostics",
            )
        ],
        source_quotes=[
            SourceQuote(
                quote_id="policy_q1",
                source_type="payer_policy",
                quote="BMI greater than or equal to 30",
                location="section 2",
            )
        ],
    )
    evidence = ChartEvidence(
        case_id=case_id,
        evidence_items=[
            EvidenceItem(
                criterion_id="mn_1",
                finding="BMI 34.2",
                quote="BMI 34.2",
                quote_location="2026-03-12 visit",
                supports_appeal=True,
            )
        ],
        criteria_met={"mn_1": True},
        source_quotes=[
            SourceQuote(
                quote_id="chart_q1",
                source_type="patient_chart",
                quote="BMI 34.2",
                location="2026-03-12 visit",
            )
        ],
    )
    guidelines = GuidelineCitations(
        case_id=case_id,
        citations=[
            GuidelineCitation(
                citation_id="g1",
                guideline_source="ADA 2024 Standards of Care",
                citation_title="Pharmacologic Therapy",
                quote="GLP-1 RAs are recommended in adults with BMI >= 30",
                supports_claim="BMI >= 30 qualifies patient for GLP-1 therapy",
            )
        ],
    )
    draft = AppealDraft(
        case_id=case_id,
        recipient_plan="ACME Health",
        subject_line="Appeal — Ozempic denial",
        paragraphs=[
            AppealParagraph(
                text="Patient's BMI of 34.2 meets the policy's stated threshold of 30.",
                citations=[
                    CitationMarker(
                        claim="Patient's BMI is 34.2",
                        source_type="patient_chart",
                        source_id="chart_q1",
                        verbatim_quote="BMI 34.2",
                    ),
                    CitationMarker(
                        claim="Policy threshold is BMI >= 30",
                        source_type="payer_policy",
                        source_id="policy_q1",
                        verbatim_quote="BMI greater than or equal to 30",
                    ),
                ],
            )
        ],
    )
    final = VerifiedAppeal(
        case_id=case_id,
        draft=draft,
        verified_citations=[
            VerifiedCitation(
                citation=draft.paragraphs[0].citations[0],
                verified=True,
                verification_method="exact_substring",
            ),
            VerifiedCitation(
                citation=draft.paragraphs[0].citations[1],
                verified=True,
                verification_method="exact_substring",
            ),
        ],
        rejected_citations=[],
        verification_pass_rate=1.0,
        ready_to_send=True,
    )

    # JSON round-trip of the whole pipeline
    j = json.dumps(
        {
            "input": PipelineInput(
                case_id=case_id,
                denial_letter_path="x.pdf",
                patient_chart_path="y.txt",
                payer_policy_path="z.pdf",
            ).model_dump(),
            "denial": denial.model_dump(),
            "policy": policy.model_dump(),
            "evidence": evidence.model_dump(),
            "guidelines": guidelines.model_dump(),
            "final": final.model_dump(),
        }
    )
    assert json.loads(j)["final"]["ready_to_send"] is True


def test_rejected_citation_shape():
    rc = RejectedCitation(
        citation=CitationMarker(
            claim="x", source_type="patient_chart", source_id="q1", verbatim_quote="y"
        ),
        rejection_reason="quote 'y' not found in patient_chart source 'q1'",
    )
    assert "not found" in rc.rejection_reason
