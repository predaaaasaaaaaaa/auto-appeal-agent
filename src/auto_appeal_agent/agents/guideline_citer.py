"""
GuidelineCiter — suggests professional-society clinical guidelines that
support the patient's appeal.

Important reliability note: unlike the other agents, GuidelineCiter does
NOT extract quotes from an input document. It draws on Claude's training
knowledge. That means the guidelines it cites CAN be hallucinated, and
the Verifier (which matches quotes against upstream SourceQuotes) cannot
guard against that failure mode.

Design contract for downstream agents:

  * The LetterWriter MUST NOT use GuidelineCitation entries as
    CitationMarkers (i.e. it should not pretend these are verifiable
    source quotes). GuidelineCitations are prose support only.
  * The appeal letter's critical claims — patient facts, policy
    criteria, prior treatments — all rest on verifiable citations to
    the denial letter, the chart, and the payer policy. Guidelines
    only add color.

Prompt-level mitigations: Claude is told to cite ONLY guidelines it is
highly confident about, from named major societies, and to prefer fewer
accurate citations over more uncertain ones.
"""
from __future__ import annotations

from typing import Any

from auto_appeal_agent.anthropic_client import call_claude_structured
from auto_appeal_agent.schemas import (
    DenialReason,
    GuidelineCitations,
    MedicalNecessityCriterion,
)

_SYSTEM_PROMPT = """\
You are a clinical-evidence specialist. Given a prior-authorization
denial and the payer's medical-necessity criteria, identify 1-4
clinical guidelines from major professional societies (AAFP, ACC, ACOG,
ACP, ACR, ADA, AHA, ASCO, IDSA, NCCN, USPSTF, equivalent international
bodies) that support the patient's appeal.

Strict rules:

  - Cite ONLY guidelines you are highly confident about. Include the
    full society name and publication year.
  - If you are uncertain about any detail of a guideline, DO NOT cite
    it. Prefer 1 accurate citation over 3 uncertain ones.
  - `citation_id` format: "guideline_qN".
  - Each `quote` should be a short (under 40 words), faithful summary of
    the guideline's recommendation. (These are NOT verbatim verifiable
    quotes from a local document; downstream stages use them as prose
    support only.)
  - `supports_claim` must name the specific appeal claim the citation
    reinforces, e.g. "BMI >= 30 qualifies the patient for GLP-1 therapy".
  - `url` may be null if you do not know the exact URL.
  - The `case_id` in your output MUST match the user's case_id.

Return your answer by calling the emit_structured_output tool with a
valid GuidelineCitations object.
"""


def _format_denial_reasons(reasons: list[DenialReason]) -> str:
    return "\n".join(f"  - {r.reason}" for r in reasons)


def _format_criteria(criteria: list[MedicalNecessityCriterion]) -> str:
    return "\n".join(f"  - {c.text}" for c in criteria)


def cite_guidelines(
    case_id: str,
    denial_reasons: list[DenialReason],
    criteria: list[MedicalNecessityCriterion],
) -> GuidelineCitations:
    """Return professional-society guideline citations supporting the appeal."""
    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Identify supporting clinical guidelines for case_id='{case_id}'.\n\n"
                f"DENIAL REASONS:\n{_format_denial_reasons(denial_reasons)}\n\n"
                f"POLICY CRITERIA:\n{_format_criteria(criteria)}\n\n"
                f"Return 1-4 high-confidence GuidelineCitations."
            ),
        }
    ]

    citations, _raw = call_claude_structured(
        output_model=GuidelineCitations,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
        max_tokens=2048,
    )
    return citations
