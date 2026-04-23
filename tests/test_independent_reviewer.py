"""
IndependentReviewer cassette test.

Builds a realistic AppealDraft (the same one used by the LetterWriter
test) and asks the reviewer to grade it. Verifies shape, that every
verdict references a real citation index, and that the reviewer agrees
the citations support the claims (since the LetterWriter test fixture
is intentionally well-formed).
"""
from __future__ import annotations

from auto_appeal_agent.agents.independent_reviewer import independent_review
from auto_appeal_agent.schemas import (
    AppealDraft,
    AppealParagraph,
    CitationMarker,
    SourceQuote,
)


def _draft_and_sources():
    """A minimal but well-supported draft, mirroring case_01."""
    sources = [
        SourceQuote(
            quote_id="policy_q1",
            source_type="payer_policy",
            quote="Body Mass Index (BMI) at or above 30 kg/m^2",
            location="medical necessity section, point 2",
        ),
        SourceQuote(
            quote_id="chart_q1",
            source_type="patient_chart",
            quote="BMI 34.2",
            location="2026-02-15 progress note",
        ),
    ]
    draft = AppealDraft(
        case_id="case_01_ozempic_bmi34",
        recipient_plan="BlueSun Health Premium HMO",
        subject_line="Appeal of prior authorization denial — Ozempic — member BS-A1234567",
        paragraphs=[
            AppealParagraph(
                heading="Medical necessity met: BMI threshold",
                text=(
                    "MEDPOL-GLP1-v3 requires a Body Mass Index (BMI) at or above "
                    "30 kg/m^2. The chart documents the patient's BMI as 34.2, "
                    "well above the threshold."
                ),
                citations=[
                    CitationMarker(
                        claim="The policy requires BMI at or above 30 kg/m^2",
                        source_type="payer_policy",
                        source_id="policy_q1",
                        verbatim_quote="Body Mass Index (BMI) at or above 30 kg/m^2",
                    ),
                    CitationMarker(
                        claim="The patient's BMI is 34.2",
                        source_type="patient_chart",
                        source_id="chart_q1",
                        verbatim_quote="BMI 34.2",
                    ),
                ],
            )
        ],
    )
    return draft, sources


def test_independent_reviewer_grades_well_formed_draft(cassette):  # noqa: ARG001
    draft, sources = _draft_and_sources()
    review = independent_review(draft, sources)

    assert review.case_id == "case_01_ozempic_bmi34"

    # Each citation must get exactly one verdict, indexed correctly.
    assert len(review.citation_verdicts) == 2
    indices = {(v.paragraph_index, v.citation_in_paragraph_index) for v in review.citation_verdicts}
    assert indices == {(0, 0), (0, 1)}

    # The draft is intentionally well-supported, so the reviewer should agree.
    verdicts = [v.verdict for v in review.citation_verdicts]
    assert "unsupported" not in verdicts, (
        f"reviewer flagged a well-supported citation as unsupported: {verdicts}"
    )

    # overall_verdict must be one of the two literals
    assert review.overall_verdict in ("sign_ready", "needs_revision")

    # Reviewer summary must be non-empty
    assert review.reviewer_summary.strip()


def test_independent_reviewer_flags_unsupported_citation(cassette):  # noqa: ARG001
    """A citation whose quote exists but doesn't support the claim should
    get marked partial or unsupported by the reviewer."""
    sources = [
        SourceQuote(
            quote_id="chart_q1",
            source_type="patient_chart",
            quote="BMI 34.2",
            location="2026-02-15 progress note",
        )
    ]
    draft = AppealDraft(
        case_id="case_bad_inference",
        recipient_plan="ACME Health",
        subject_line="Appeal — bad inference",
        paragraphs=[
            AppealParagraph(
                heading="A claim the quote doesn't actually support",
                text=(
                    "The chart establishes that the patient has documented "
                    "type 1 diabetes, citing 'BMI 34.2'."
                ),
                citations=[
                    CitationMarker(
                        # The cited quote does NOT establish T1DM at all.
                        claim="The patient has type 1 diabetes",
                        source_type="patient_chart",
                        source_id="chart_q1",
                        verbatim_quote="BMI 34.2",
                    )
                ],
            )
        ],
    )
    review = independent_review(draft, sources)
    assert review.case_id == "case_bad_inference"
    assert len(review.citation_verdicts) == 1
    v = review.citation_verdicts[0]
    assert v.verdict in ("partial", "unsupported"), (
        f"reviewer should have flagged inference, got verdict={v.verdict} "
        f"rationale={v.rationale}"
    )
    assert review.overall_verdict == "needs_revision"
