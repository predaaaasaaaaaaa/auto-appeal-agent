"""
Verifier unit tests.

Plain-language summary: these test the Verifier directly (not via the
orchestrator), with synthetic AppealDraft + SourceQuote objects. They
need no API calls, so they run in the default `pytest` suite and form
the innermost reliability gate.

Full-pipeline end-to-end tests live in tests/test_fixtures.py and are
marked @pytest.mark.integration.
"""
from __future__ import annotations

from auto_appeal_agent.agents.verifier import verify_appeal
from auto_appeal_agent.schemas import (
    AppealDraft,
    AppealParagraph,
    CitationMarker,
    SourceQuote,
)


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
