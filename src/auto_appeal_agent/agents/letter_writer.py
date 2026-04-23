"""
LetterWriter — assembles the draft appeal letter.

Plain-language summary: takes everything the earlier agents found (denial,
policy criteria, chart evidence, guidelines) and produces a draft appeal
letter. Every factual claim in the draft is tagged with a CitationMarker
pointing back at an upstream SourceQuote, so the Verifier can re-check it.

Phase 0 status: STUBBED. Phase 1 replaces with a Claude call that writes
a proper professional letter.
"""
from __future__ import annotations

from auto_appeal_agent.schemas import (
    AppealDraft,
    AppealParagraph,
    ChartEvidence,
    CitationMarker,
    DenialAnalysis,
    GuidelineCitations,
    PolicyCriteria,
)


def write_appeal(
    case_id: str,
    denial: DenialAnalysis,
    policy: PolicyCriteria,
    evidence: ChartEvidence,
    guidelines: GuidelineCitations,
) -> AppealDraft:
    """Return a draft appeal letter with cited factual claims.

    Args:
        case_id: Stable ID for this case.
        denial: What the insurer said.
        policy: What the insurer's policy actually requires.
        evidence: What the patient's chart shows.
        guidelines: Supporting professional-society guidelines.

    Returns:
        An AppealDraft with placeholder content; shape is valid and
        every paragraph cites at least one upstream SourceQuote.
    """
    del guidelines  # stub does not use every input yet
    return AppealDraft(
        case_id=case_id,
        recipient_plan=denial.member_info.plan_name,
        subject_line=f"[stub] Appeal re: {denial.requested_service}",
        paragraphs=[
            AppealParagraph(
                heading="Medical necessity met",
                text=(
                    "[stub] The patient's chart documents "
                    f"{evidence.evidence_items[0].finding}, which meets the "
                    f"criterion '{policy.criteria[0].text}'."
                ),
                citations=[
                    CitationMarker(
                        claim="[stub] the chart documents the evidence",
                        source_type="patient_chart",
                        source_id=evidence.source_quotes[0].quote_id,
                        verbatim_quote=evidence.source_quotes[0].quote,
                    ),
                    CitationMarker(
                        claim="[stub] the policy requires this criterion",
                        source_type="payer_policy",
                        source_id=policy.source_quotes[0].quote_id,
                        verbatim_quote=policy.source_quotes[0].quote,
                    ),
                ],
            )
        ],
    )
