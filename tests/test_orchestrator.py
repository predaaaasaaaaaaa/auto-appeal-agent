"""
Orchestrator smoke tests.

Plain-language summary: these run the whole pipeline end-to-end on the
current stubs and assert that:
  (1) it finishes without error,
  (2) the shape of the final VerifiedAppeal is valid,
  (3) the Verifier correctly passes matching citations and rejects
      mismatched ones.

These tests DO NOT call the real Anthropic API — the stubs handle that.
"""
from __future__ import annotations

from pathlib import Path

from auto_appeal_agent.agents.verifier import verify_appeal
from auto_appeal_agent.orchestrator import run_pipeline
from auto_appeal_agent.schemas import (
    AppealDraft,
    AppealParagraph,
    CitationMarker,
    PipelineInput,
    SourceQuote,
)


def _smoke_input() -> PipelineInput:
    return PipelineInput(
        case_id="smoke",
        denial_letter_path="x.pdf",
        patient_chart_path="y.txt",
        payer_policy_path="z.pdf",
    )


def test_stub_pipeline_runs_end_to_end():
    result = run_pipeline(_smoke_input())
    assert result.case_id == "smoke"


def test_stub_pipeline_produces_ready_appeal():
    result = run_pipeline(_smoke_input())
    assert result.ready_to_send is True
    assert result.verification_pass_rate == 1.0


def test_stub_pipeline_has_expected_citation_counts():
    result = run_pipeline(_smoke_input())
    # LetterWriter stub produces one paragraph with two citations
    # (chart + policy). Both should verify against upstream source quotes.
    assert len(result.verified_citations) == 2
    assert len(result.rejected_citations) == 0


def test_verifier_rejects_quote_not_in_source():
    """If the LetterWriter hallucinates a quote, the Verifier must catch it."""
    bad_draft = AppealDraft(
        case_id="bad",
        recipient_plan="ACME",
        subject_line="subject",
        paragraphs=[
            AppealParagraph(
                text="Fabricated claim.",
                citations=[
                    CitationMarker(
                        claim="patient was on fire",
                        source_type="patient_chart",
                        source_id="chart_q1",
                        verbatim_quote="HALLUCINATION NOT IN SOURCE",
                    )
                ],
            )
        ],
    )
    sources = [
        SourceQuote(
            quote_id="chart_q1",
            source_type="patient_chart",
            quote="BMI 34.2",
            location="2026-03-12 visit",
        )
    ]
    verified = verify_appeal(bad_draft, sources)
    assert verified.ready_to_send is False
    assert verified.verification_pass_rate == 0.0
    assert len(verified.rejected_citations) == 1
    assert "not found" in verified.rejected_citations[0].rejection_reason.lower()


def test_verifier_rejects_unknown_source_id():
    draft = AppealDraft(
        case_id="bad",
        recipient_plan="ACME",
        subject_line="subject",
        paragraphs=[
            AppealParagraph(
                text="Claim with dangling reference.",
                citations=[
                    CitationMarker(
                        claim="x",
                        source_type="patient_chart",
                        source_id="does_not_exist",
                        verbatim_quote="BMI 34.2",
                    )
                ],
            )
        ],
    )
    verified = verify_appeal(draft, [])
    assert verified.ready_to_send is False
    assert len(verified.rejected_citations) == 1
    assert "not found" in verified.rejected_citations[0].rejection_reason.lower()


def test_verifier_tolerates_whitespace_and_case():
    """Real-world denial letters have messy whitespace; the verifier normalizes."""
    draft = AppealDraft(
        case_id="whitespace",
        recipient_plan="ACME",
        subject_line="subject",
        paragraphs=[
            AppealParagraph(
                text="Whitespace differences tolerated.",
                citations=[
                    CitationMarker(
                        claim="x",
                        source_type="patient_chart",
                        source_id="chart_q1",
                        verbatim_quote="bmi 34.2",
                    )
                ],
            )
        ],
    )
    sources = [
        SourceQuote(
            quote_id="chart_q1",
            source_type="patient_chart",
            quote="BMI   34.2",  # extra whitespace, different case
            location="2026-03-12 visit",
        )
    ]
    verified = verify_appeal(draft, sources)
    assert verified.ready_to_send is True
    assert verified.verified_citations[0].verification_method == "normalized_substring"
