"""
LetterWriter integration test.

This is the Phase-1 reliability showpiece: hand-crafted upstream outputs
are piped through the real LetterWriter, then through the real Verifier.
Pass condition: `ready_to_send=True` and `verification_pass_rate=1.0`.

If this test fails, it means either
  (a) the LetterWriter hallucinated a citation, or
  (b) the LetterWriter paraphrased instead of quoting verbatim.

Both are reliability regressions that block the whole project.
"""
from __future__ import annotations

import pytest

from auto_appeal_agent.agents.letter_writer import write_appeal
from auto_appeal_agent.agents.verifier import verify_appeal
from auto_appeal_agent.schemas import (
    ChartEvidence,
    DenialAnalysis,
    DenialReason,
    EvidenceItem,
    GuidelineCitation,
    GuidelineCitations,
    MedicalNecessityCriterion,
    MemberInfo,
    PolicyCriteria,
    SourceQuote,
)


def _case_01_upstream():
    """Hand-crafted upstream outputs for case_01 Ozempic denial."""
    denial = DenialAnalysis(
        case_id="case_01_ozempic_bmi34",
        member_info=MemberInfo(
            member_name="Jane A. Doe",
            member_id="BS-A1234567",
            date_of_birth="May 14, 1978",
            plan_name="BlueSun Health Premium HMO",
        ),
        requested_service="semaglutide (Ozempic) 1mg weekly subcutaneous injection",
        denial_date="April 1, 2026",
        denial_reasons=[
            DenialReason(
                reason="Not medically necessary",
                code="MN-12",
                quote="Not medically necessary",
                quote_location="page 1",
            )
        ],
        source_quotes=[
            SourceQuote(
                quote_id="denial_q1",
                source_type="denial_letter",
                quote=(
                    "your prior authorization request for semaglutide (Ozempic) 1mg "
                    "weekly subcutaneous injection has been DENIED"
                ),
                location="page 1, paragraph 1",
            ),
            SourceQuote(
                quote_id="denial_q2",
                source_type="denial_letter",
                quote="Member does not meet all criteria for GLP-1 receptor agonist therapy",
                location="page 1, reason",
            ),
        ],
    )

    policy = PolicyCriteria(
        case_id="case_01_ozempic_bmi34",
        policy_name="MEDPOL-GLP1-v3",
        policy_effective_date="January 1, 2026",
        criteria=[
            MedicalNecessityCriterion(
                criterion_id="mn_1",
                text="BMI at or above 30 kg/m^2",
                quote="Body Mass Index (BMI) at or above 30 kg/m^2",
                quote_location="medical necessity section",
                category="diagnostics",
            ),
            MedicalNecessityCriterion(
                criterion_id="mn_2",
                text=(
                    "Documented participation in supervised diet and exercise "
                    "for at least six months"
                ),
                quote=(
                    "supervised program of reduced-calorie diet, increased "
                    "physical activity, and behavior modification for a minimum "
                    "of six months"
                ),
                quote_location="medical necessity section",
                category="prior_treatments",
            ),
        ],
        source_quotes=[
            SourceQuote(
                quote_id="policy_q1",
                source_type="payer_policy",
                quote="Body Mass Index (BMI) at or above 30 kg/m^2",
                location="medical necessity section, point 2",
            ),
            SourceQuote(
                quote_id="policy_q2",
                source_type="payer_policy",
                quote=(
                    "supervised program of reduced-calorie diet, increased "
                    "physical activity, and behavior modification for a minimum "
                    "of six months"
                ),
                location="medical necessity section, point 3",
            ),
        ],
    )

    evidence = ChartEvidence(
        case_id="case_01_ozempic_bmi34",
        evidence_items=[
            EvidenceItem(
                criterion_id="mn_1",
                finding="Patient's recorded BMI is 34.2",
                quote="BMI 34.2",
                quote_location="2026-02-15 progress note",
                supports_appeal=True,
            ),
            EvidenceItem(
                criterion_id="mn_2",
                finding="10 months of supervised Weight Watchers participation",
                quote="Patient has attended 21 of 24 scheduled Weight Watchers group sessions",
                quote_location="2025-11-20 progress note",
                supports_appeal=True,
            ),
        ],
        criteria_met={"mn_1": True, "mn_2": True},
        source_quotes=[
            SourceQuote(
                quote_id="chart_q1",
                source_type="patient_chart",
                quote="BMI 34.2",
                location="2026-02-15 progress note",
            ),
            SourceQuote(
                quote_id="chart_q2",
                source_type="patient_chart",
                quote="Patient has attended 21 of 24 scheduled Weight Watchers group sessions",
                location="2025-11-20 progress note",
            ),
        ],
    )

    # Corpus-backed guideline citation. citation_id matches an excerpt
    # in fixtures/guidelines/corpus.json, and source_quotes echoes that
    # excerpt as a SourceQuote so the Verifier can substring-check
    # any CitationMarker the LetterWriter emits against it.
    guideline_quote_text = (
        "Adults with a BMI of 30 kg/m2 or greater, or a BMI of 27 kg/m2 or "
        "greater with weight-related comorbidities such as hypertension or "
        "type 2 diabetes mellitus, should be offered comprehensive lifestyle "
        "interventions, and pharmacotherapy is an appropriate adjunct in "
        "these BMI categories when lifestyle measures alone do not achieve "
        "sufficient weight loss."
    )
    guidelines = GuidelineCitations(
        case_id="case_01_ozempic_bmi34",
        citations=[
            GuidelineCitation(
                citation_id="guideline_aha_acc_tos_2013_q1",
                guideline_source=(
                    "American Heart Association / American College of "
                    "Cardiology / The Obesity Society"
                ),
                citation_title=(
                    "2013 AHA/ACC/TOS Guideline for the Management of "
                    "Overweight and Obesity in Adults"
                ),
                quote=guideline_quote_text,
                url="https://www.ahajournals.org/doi/10.1161/01.cir.0000437739.71477.ee",
                supports_claim=(
                    "BMI >= 30 with weight-related comorbidity qualifies "
                    "the patient for obesity pharmacotherapy"
                ),
            )
        ],
        source_quotes=[
            SourceQuote(
                quote_id="guideline_aha_acc_tos_2013_q1",
                source_type="clinical_guideline",
                quote=guideline_quote_text,
                location=(
                    "American Heart Association / American College of "
                    "Cardiology / The Obesity Society 2013 — Treatment "
                    "recommendations"
                ),
            )
        ],
    )

    return denial, policy, evidence, guidelines


def test_letter_writer_produces_verifiable_appeal(cassette):  # noqa: ARG001
    denial, policy, evidence, guidelines = _case_01_upstream()

    draft = write_appeal(
        case_id="case_01_ozempic_bmi34",
        denial=denial,
        policy=policy,
        evidence=evidence,
        guidelines=guidelines,
    )

    # Structural checks
    assert draft.case_id == "case_01_ozempic_bmi34"
    assert "BlueSun" in draft.recipient_plan
    assert len(draft.paragraphs) >= 3, "expect at least 3 paragraphs"
    assert any(p.citations for p in draft.paragraphs), "expect at least one CitationMarker"

    # Hand all upstream source quotes — including guideline-corpus
    # excerpts — to the Verifier so guideline CitationMarkers get the
    # same substring re-check as denial/policy/chart ones.
    all_quotes = (
        denial.source_quotes
        + policy.source_quotes
        + evidence.source_quotes
        + guidelines.source_quotes
    )
    verified = verify_appeal(draft, all_quotes)

    # The reliability gate.
    if not verified.ready_to_send:
        rejected_lines = "\n".join(
            f"    - source_id={r.citation.source_id} "
            f"quote={r.citation.verbatim_quote!r}\n      reason: {r.rejection_reason}"
            for r in verified.rejected_citations
        )
        pytest.fail(
            "LetterWriter produced unverifiable citations:\n"
            f"  verification_pass_rate={verified.verification_pass_rate:.3f}\n"
            f"  rejected_citations ({len(verified.rejected_citations)}):\n"
            f"{rejected_lines}"
        )

    assert verified.verification_pass_rate == 1.0
    assert len(verified.verified_citations) >= 2, (
        "expect at least two verified citations (chart + policy)"
    )
    # Every verified citation must point at a known source type. Guideline
    # citations are now first-class, so clinical_guideline is allowed too.
    assert all(
        vc.citation.source_type
        in ("denial_letter", "payer_policy", "patient_chart", "clinical_guideline")
        for vc in verified.verified_citations
    )
