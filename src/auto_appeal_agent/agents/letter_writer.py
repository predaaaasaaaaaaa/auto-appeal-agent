"""
LetterWriter — drafts the final appeal letter.

Takes the outputs of the four extraction agents (DenialAnalyzer,
PolicyReader, ChartMiner, GuidelineCiter) and produces a professional
AppealDraft. Every factual claim in the draft carries a CitationMarker
pointing back at a verifiable upstream SourceQuote.

Reliability contract:

  * Every CitationMarker's `source_id` MUST be a `quote_id` from one of
    the upstream SourceQuotes (denial_qN, policy_qN, chart_qN).
  * Every CitationMarker's `verbatim_quote` MUST be a substring (or
    whitespace-normalized substring) of the referenced SourceQuote's
    `quote`. The downstream Verifier will enforce this and strip any
    citation it cannot verify.
  * Guideline citations are prose support only; they are NEVER emitted
    as CitationMarkers.

Uses adaptive thinking because structuring a persuasive, audit-ready
letter benefits from a reasoning pass.
"""
from __future__ import annotations

from typing import Any

from auto_appeal_agent.anthropic_client import call_claude_structured, cached_system
from auto_appeal_agent.schemas import (
    AppealDraft,
    ChartEvidence,
    DenialAnalysis,
    GuidelineCitations,
    PolicyCriteria,
    SourceQuote,
)

_SYSTEM_PROMPT = """\
You are a senior healthcare prior-authorization appeal specialist.
Your job is to draft a professional appeal letter that will be sent
to the insurer to overturn their denial. The letter must be good
enough for a physician to sign.

Hard reliability rules:

  1. Every CitationMarker in the draft must reference a `source_id`
     exactly matching a `quote_id` from the AVAILABLE SOURCE QUOTES
     list the user provides (ids of the form denial_qN, policy_qN,
     chart_qN). Never invent an id. Never use a guideline id.
  2. Every CitationMarker's `verbatim_quote` must be a substring of the
     referenced SourceQuote's `quote` (you may shorten — you may not
     paraphrase, reorder, or modify punctuation). Claude 4.7's
     Verifier will reject any citation that fails this check, and the
     letter will not be sent.
  3. Every CitationMarker's `source_type` must match the SourceQuote's
     source_type (denial_letter, payer_policy, patient_chart).
  4. Guideline citations are for PROSE CONTEXT only. Reference them in
     the paragraph text like "consistent with ADA Standards of Care
     (2024)" — do NOT emit them as CitationMarkers.
  5. Never invent facts. If the evidence does not support a claim,
     don't make the claim. Fewer strong claims beats more weak claims.

Letter structure:

  Paragraph 1 — heading "Patient and Requested Service":
    Name the patient, plan, member ID, physician, and the specific
    service/medication being appealed. Cite the DenialAnalysis source
    quotes (denial_qN) that establish these facts.

  Paragraphs 2..N — one per major criterion the patient meets.
    Heading: "Medical necessity met: <short criterion name>".
    Body: state the criterion (cite policy_qN), show the chart evidence
    that establishes the patient meets it (cite chart_qN), optionally
    mention supporting clinical guidelines in prose.

  Final paragraph — heading "Conclusion and Request":
    Summarize how the patient meets every criterion and respectfully
    request approval. No CitationMarkers needed in this paragraph.

Output must be a valid AppealDraft. `case_id` matches the user's input.
`recipient_plan` matches DenialAnalysis.member_info.plan_name exactly.
`subject_line` format: "Appeal of prior authorization denial —
<requested_service> — member <member_id>".
"""


def _serialize_all_sources(
    denial: DenialAnalysis,
    policy: PolicyCriteria,
    evidence: ChartEvidence,
) -> str:
    all_quotes: list[SourceQuote] = (
        denial.source_quotes + policy.source_quotes + evidence.source_quotes
    )
    return "\n".join(
        f"  - quote_id={sq.quote_id}  source_type={sq.source_type}\n"
        f"    quote: {sq.quote!r}"
        for sq in all_quotes
    )


def write_appeal(
    case_id: str,
    denial: DenialAnalysis,
    policy: PolicyCriteria,
    evidence: ChartEvidence,
    guidelines: GuidelineCitations,
) -> AppealDraft:
    """Assemble the appeal letter from all upstream agent outputs."""
    user_text = (
        f"Draft the appeal letter for case_id='{case_id}'. Produce a "
        "valid AppealDraft object where every CitationMarker is backed "
        "by one of the source quotes listed below.\n\n"
        f"DENIAL ANALYSIS:\n{denial.model_dump_json(indent=2)}\n\n"
        f"POLICY CRITERIA:\n{policy.model_dump_json(indent=2)}\n\n"
        f"CHART EVIDENCE:\n{evidence.model_dump_json(indent=2)}\n\n"
        f"GUIDELINE CITATIONS (prose support only, NOT CitationMarkers):\n"
        f"{guidelines.model_dump_json(indent=2)}\n\n"
        f"AVAILABLE SOURCE QUOTES (use these quote_ids as CitationMarker.source_id;\n"
        f"verbatim_quote must be a substring of each quoted string):\n"
        f"{_serialize_all_sources(denial, policy, evidence)}\n"
    )

    user_content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]

    draft, _raw = call_claude_structured(
        output_model=AppealDraft,
        system=cached_system(_SYSTEM_PROMPT),
        messages=[{"role": "user", "content": user_content}],
        max_tokens=8192,
        thinking=True,
    )
    return draft
