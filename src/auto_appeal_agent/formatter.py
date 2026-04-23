"""
formatter.py — render a VerifiedAppeal as human-readable Markdown.

Used by `scripts/run_case.py` to write the agent's output to disk in a
form a person can read end-to-end (the appeal letter), with a separate
verification report showing every citation, where it came from, and
whether the Verifier passed it.
"""
from __future__ import annotations

from datetime import date

from auto_appeal_agent.schemas import VerifiedAppeal


def render_appeal_letter(verified: VerifiedAppeal) -> str:
    """Render the appeal letter (without the verification audit) as Markdown."""
    draft = verified.draft
    today = date.today().isoformat()

    lines: list[str] = [
        f"# {draft.subject_line}",
        "",
        f"**To:** {draft.recipient_plan}",
        f"**Date:** {today}",
        f"**Case ID:** {draft.case_id}",
        "",
        "---",
        "",
    ]

    for paragraph in draft.paragraphs:
        if paragraph.heading:
            lines.append(f"## {paragraph.heading}")
            lines.append("")
        lines.append(paragraph.text)
        lines.append("")
        if paragraph.citations:
            cite_ids = ", ".join(f"`{c.source_id}`" for c in paragraph.citations)
            lines.append(f"_Citations: {cite_ids}_")
            lines.append("")

    if verified.ready_to_send:
        lines.append("---")
        lines.append("")
        lines.append(
            f"_All {len(verified.verified_citations)} factual citations in this letter "
            f"have been verified against their source documents._"
        )
    else:
        lines.append("---")
        lines.append("")
        lines.append(
            f"_DRAFT — {len(verified.rejected_citations)} unverified citation(s) "
            "were stripped. See verification report._"
        )

    return "\n".join(lines)


def render_verification_report(verified: VerifiedAppeal) -> str:
    """Render the citation-by-citation audit as Markdown."""
    lines: list[str] = [
        f"# Verification report — {verified.draft.case_id}",
        "",
        f"**Pass rate:** {verified.verification_pass_rate:.1%}",
        f"**Ready to send:** {'YES' if verified.ready_to_send else 'NO'}",
        f"**Verified citations:** {len(verified.verified_citations)}",
        f"**Rejected citations:** {len(verified.rejected_citations)}",
        "",
    ]

    if verified.verified_citations:
        lines.append("## Verified citations")
        lines.append("")
        for vc in verified.verified_citations:
            lines.append(
                f"- **{vc.citation.source_id}** "
                f"(`{vc.citation.source_type}`, {vc.verification_method})"
            )
            lines.append(f"  - Claim: {vc.citation.claim}")
            lines.append(f"  - Quote: _{vc.citation.verbatim_quote!r}_")
            if vc.notes:
                lines.append(f"  - Notes: {vc.notes}")
        lines.append("")

    if verified.rejected_citations:
        lines.append("## Rejected citations (NOT in the final letter)")
        lines.append("")
        for rc in verified.rejected_citations:
            lines.append(
                f"- **{rc.citation.source_id}** (`{rc.citation.source_type}`)"
            )
            lines.append(f"  - Claim: {rc.citation.claim}")
            lines.append(f"  - Attempted quote: _{rc.citation.verbatim_quote!r}_")
            lines.append(f"  - Reason: {rc.rejection_reason}")
        lines.append("")

    return "\n".join(lines)
