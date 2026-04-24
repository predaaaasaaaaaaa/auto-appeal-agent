"""
IndependentReviewer — fresh-context second opinion on the draft appeal.

Plain-language summary: after the substring Verifier confirms each
citation literally exists in its source, this agent asks Claude — in a
brand-new conversation with no shared context with the LetterWriter —
whether each citation actually *supports* the claim it's attached to.
This catches a class of error the substring Verifier can't:

  * The quote exists in the source, but the LetterWriter used it to
    support a claim it doesn't actually establish.
  * The letter omits an argument that any clinician would expect.

The review never blocks the letter from shipping — its output is
attached to VerifiedAppeal.second_pass_review and rendered in the UI
so a human reviewer can decide whether to accept the draft as-is.
"""
from __future__ import annotations

from typing import Any

from auto_appeal_agent.anthropic_client import call_claude_structured, cached_system
from auto_appeal_agent.schemas import (
    AppealDraft,
    AppealReview,
    SourceQuote,
)

_SYSTEM_PROMPT = """\
You are a senior prior-authorization appeals reviewer doing QA on a
draft appeal letter that another agent wrote. You have NOT seen the
drafting agent's reasoning — only the final draft, the source quotes
the drafting agent had access to, and the appeal task.

Your job is to answer two questions:

  1. For each CitationMarker in the draft, does the cited verbatim
     quote actually SUPPORT the claim it's attached to? Verdicts:
       - "supports"     — the quote clearly establishes the claim.
       - "partial"      — the quote is relevant but incomplete or weak.
       - "unsupported"  — the quote is in the source but does not
                          actually establish the claim being made.
     Provide a one-sentence rationale for each verdict. Be strict:
     when in doubt, mark "partial".

  2. At a higher level, are there concerns a physician should consider
     before signing? Examples:
       - missing argument the policy obviously requires,
       - tone/professionalism issues,
       - clinical claim that's overstated,
       - cited guideline that's not the right one for this scenario.

Output an AppealReview via the emit_structured_output tool. Set
`overall_verdict` to "sign_ready" only when every citation verdict
is "supports" AND there are no high_level_concerns.

Index citations by paragraph_index (0-based across draft.paragraphs)
and citation_in_paragraph_index (0-based within that paragraph's
citations list).
"""


def _format_citations(draft: AppealDraft) -> str:
    """Render the draft's claims and citations in a stable indexed form
    so the reviewer can refer to each one unambiguously."""
    lines: list[str] = []
    for pi, paragraph in enumerate(draft.paragraphs):
        if not paragraph.citations:
            continue
        for ci, c in enumerate(paragraph.citations):
            lines.append(
                f"  [paragraph={pi}, citation={ci}] source_id={c.source_id} "
                f"source_type={c.source_type}\n"
                f"    claim: {c.claim}\n"
                f"    quoted from source: {c.verbatim_quote!r}"
            )
    return "\n".join(lines) if lines else "  (no citations to review)"


def _format_sources(source_quotes: list[SourceQuote]) -> str:
    return "\n".join(
        f"  - quote_id={sq.quote_id} ({sq.source_type})\n"
        f"    full_text: {sq.quote!r}"
        for sq in source_quotes
    )


def _format_paragraphs(draft: AppealDraft) -> str:
    parts: list[str] = []
    for pi, p in enumerate(draft.paragraphs):
        head = f"[paragraph={pi}]"
        if p.heading:
            head += f" {p.heading}"
        parts.append(head + "\n" + p.text)
    return "\n\n".join(parts)


def independent_review(
    draft: AppealDraft,
    source_quotes: list[SourceQuote],
) -> AppealReview:
    """Return a fresh-context review of the draft appeal."""
    user_text = (
        f"Review the draft appeal letter below for case_id='{draft.case_id}'.\n\n"
        f"DRAFT LETTER (paragraphs in order):\n{_format_paragraphs(draft)}\n\n"
        f"CITATIONS TO REVIEW (one verdict each):\n"
        f"{_format_citations(draft)}\n\n"
        f"AVAILABLE SOURCE QUOTES (for cross-reference):\n"
        f"{_format_sources(source_quotes)}\n\n"
        f"Return an AppealReview via emit_structured_output. case_id must "
        f"match '{draft.case_id}'."
    )
    user_content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]

    # max_retries=0: a ValidationError from the reviewer is almost always
    # a prompt/schema mismatch on big drafts, not a transient failure.
    # Retrying burns tokens without changing the outcome. The orchestrator
    # catches the exception and proceeds without the review.
    review, _raw = call_claude_structured(
        output_model=AppealReview,
        system=cached_system(_SYSTEM_PROMPT),
        messages=[{"role": "user", "content": user_content}],
        # 8k gives adaptive thinking headroom for per-citation verdicts
        # on typical drafts. Raise if reviews start truncating.
        max_tokens=8192,
        thinking=True,
        max_retries=0,
    )
    return review
