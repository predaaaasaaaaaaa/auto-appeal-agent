"""
Verifier — re-reads every citation and strips any it cannot verify.

Plain-language summary: this is the project's reliability guarantee.
The LetterWriter produces a draft where each factual claim is tagged with
a CitationMarker (a "receipt" pointing at a specific SourceQuote). The
Verifier ignores the draft's prose and does an independent pass: for
every CitationMarker, it looks at the original SourceQuote and checks
whether the claimed `verbatim_quote` actually appears there. Anything
that doesn't verify is moved to `rejected_citations` and the letter is
NOT marked ready-to-send. No hallucinated citation ever ships.

Phase 0 status: real string-match logic implemented (this is the core
reliability mechanism — we don't want to stub it). Phase 2 may add
fuzzy/normalized matching and an independent-Claude second opinion.
"""
from __future__ import annotations

from auto_appeal_agent.schemas import (
    AppealDraft,
    RejectedCitation,
    SourceQuote,
    VerifiedAppeal,
    VerifiedCitation,
)


def _normalize(text: str) -> str:
    """Collapse whitespace and lowercase for lenient substring checks."""
    return " ".join(text.lower().split())


def verify_appeal(
    draft: AppealDraft,
    source_quotes: list[SourceQuote],
) -> VerifiedAppeal:
    """Re-check every citation in the draft against its source.

    Args:
        draft: The LetterWriter's draft.
        source_quotes: Every SourceQuote captured by upstream agents,
            indexed internally by `quote_id`.

    Returns:
        A VerifiedAppeal. `ready_to_send` is True only when every
        citation verified and `verification_pass_rate` is 1.0.
    """
    source_by_id = {sq.quote_id: sq for sq in source_quotes}

    verified: list[VerifiedCitation] = []
    rejected: list[RejectedCitation] = []

    for paragraph in draft.paragraphs:
        for citation in paragraph.citations:
            source = source_by_id.get(citation.source_id)
            if source is None:
                rejected.append(
                    RejectedCitation(
                        citation=citation,
                        rejection_reason=(
                            f"source_id '{citation.source_id}' not found in upstream quotes"
                        ),
                    )
                )
                continue
            if source.source_type != citation.source_type:
                rejected.append(
                    RejectedCitation(
                        citation=citation,
                        rejection_reason=(
                            f"source_type mismatch: citation={citation.source_type} "
                            f"vs source={source.source_type}"
                        ),
                    )
                )
                continue

            exact = citation.verbatim_quote in source.quote
            if exact:
                verified.append(
                    VerifiedCitation(
                        citation=citation,
                        verified=True,
                        verification_method="exact_substring",
                    )
                )
                continue

            normalized_hit = _normalize(citation.verbatim_quote) in _normalize(source.quote)
            if normalized_hit:
                verified.append(
                    VerifiedCitation(
                        citation=citation,
                        verified=True,
                        verification_method="normalized_substring",
                        notes="matched after whitespace/case normalization",
                    )
                )
                continue

            rejected.append(
                RejectedCitation(
                    citation=citation,
                    rejection_reason=(
                        f"verbatim_quote not found in source '{citation.source_id}'"
                    ),
                )
            )

    total = len(verified) + len(rejected)
    pass_rate = 1.0 if total == 0 else len(verified) / total
    ready = (pass_rate == 1.0) and len(verified) > 0

    return VerifiedAppeal(
        case_id=draft.case_id,
        draft=draft,
        verified_citations=verified,
        rejected_citations=rejected,
        verification_pass_rate=pass_rate,
        ready_to_send=ready,
    )
