"""
DenialAnalyzer — reads the insurer's denial letter.

Plain-language summary: when an insurance company refuses to pay for a
treatment, they send a denial letter. This module's job is to read that
letter and pull out the structured facts we need:

  * who the patient is (name, member ID, plan name),
  * what service was requested (e.g. "Ozempic 1mg weekly"),
  * why it was denied (plain-language reasons plus any denial codes),
  * verbatim quotes from the letter the Verifier can re-check later.

Phase 0 status: STUBBED. Returns a minimal valid shape so the orchestrator
and tests run end-to-end. Phase 1 replaces the stub with a real Claude Opus
4.7 call using high-resolution vision on the PDF.
"""
from __future__ import annotations

from pathlib import Path

from auto_appeal_agent.schemas import (
    DenialAnalysis,
    DenialReason,
    MemberInfo,
    SourceQuote,
)


def analyze_denial(case_id: str, denial_letter_path: Path) -> DenialAnalysis:
    """Return a structured analysis of the denial letter.

    Args:
        case_id: Stable ID for this case (e.g. "case_01_ozempic").
        denial_letter_path: Path to the denial letter PDF (unused in stub).

    Returns:
        A DenialAnalysis with placeholder content; shape is valid.
    """
    del denial_letter_path  # stub does not read the file yet
    return DenialAnalysis(
        case_id=case_id,
        member_info=MemberInfo(
            member_name="[stub] Jane Doe",
            member_id="[stub] A00000",
            plan_name="[stub] ACME Health",
        ),
        requested_service="[stub] requested service",
        denial_reasons=[
            DenialReason(
                reason="[stub] not medically necessary",
                code="STUB-1",
                quote="[stub] the requested service is not medically necessary",
                quote_location="[stub] page 1",
            )
        ],
        source_quotes=[
            SourceQuote(
                quote_id="denial_q1",
                source_type="denial_letter",
                quote="[stub] the requested service is not medically necessary",
                location="[stub] page 1",
            )
        ],
    )
