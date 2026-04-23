"""
PolicyReader — reads the insurer's medical policy and extracts the
structured list of criteria a patient must meet for coverage.

Design choice: text-only (not vision).

Payer medical policies are digital documents, published by the insurer.
Copy-pasting from the PDF's machine-readable text layer is character-
for-character exact, which is essential because the Verifier matches
source quotes as substrings of the source text. Vision OCR, by contrast,
occasionally substitutes visually-similar characters (I/l/1, O/0) in
ways that would make verbatim matching fail on legitimate quotes.

This agent also showcases Claude 4.7's 1M-token context: we can fit a
full long policy document, plus a thorough extraction prompt, in a
single request with room to spare.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from auto_appeal_agent.anthropic_client import call_claude_structured
from auto_appeal_agent.pdf_utils import extract_text
from auto_appeal_agent.schemas import PolicyCriteria

_SYSTEM_PROMPT = """\
You are a healthcare prior-authorization specialist. Your job is to read
an insurer's medical policy document and extract every medical-necessity
criterion a patient must meet for coverage of the relevant service.

You MUST follow these rules:

  - Every `quote` field must be a VERBATIM substring of the policy
    document, character-for-character. Never paraphrase. Never
    summarize. Never change punctuation or whitespace.
  - Every `source_quote` entry must have a stable `quote_id` of the form
    "policy_qN" where N starts at 1 and increments.
  - Every `source_quote` must have `source_type = "payer_policy"`.
  - Every MedicalNecessityCriterion must have a unique `criterion_id`
    of the form "mn_N".
  - `category` must be one of: clinical_history, diagnostics,
    prior_treatments, functional_status, contraindications, other.
  - Extract EVERY testable clinical criterion. If the policy says
    "all of the following must be met" and lists four items, produce
    four criteria.
  - Do NOT include administrative boilerplate (e.g. "submit appeals
    within 60 days", section headers with no clinical content).
  - If the policy has step-therapy requirements, include them as their
    own criterion (category = prior_treatments).
  - The `case_id` in your output MUST match the one in the user's
    request.

Return your answer by calling the emit_structured_output tool with a
valid PolicyCriteria object.
"""


def read_policy(case_id: str, payer_policy_path) -> PolicyCriteria:
    """Read the payer policy and return structured medical-necessity criteria."""
    policy_text = extract_text(Path(payer_policy_path))

    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Extract every medical-necessity criterion from the payer "
                f"policy below for case_id='{case_id}'. Return the full "
                f"structured PolicyCriteria object. Reminder: every quote "
                f"must be VERBATIM from the policy text.\n\n"
                f"POLICY DOCUMENT:\n{policy_text}"
            ),
        }
    ]

    policy, _raw = call_claude_structured(
        output_model=PolicyCriteria,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
        max_tokens=4096,
    )
    return policy
