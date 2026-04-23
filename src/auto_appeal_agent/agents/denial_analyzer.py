"""
DenialAnalyzer — reads the insurer's denial letter via high-res vision.

Plain-language summary: converts each page of the denial-letter PDF into
a high-resolution image (rendered at 150 DPI, comfortably within Claude
4.7's 2576-pixel limit), and asks Claude to extract a structured
DenialAnalysis. The prompt demands that every `quote` field be a
verbatim character-for-character substring of the letter — anything
paraphrased will be caught downstream by the Verifier.

This is the first agent that replaces its stub with a real Claude call.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from auto_appeal_agent.anthropic_client import call_claude_structured, cached_system
from auto_appeal_agent.pdf_utils import render_pdf_to_image_blocks
from auto_appeal_agent.schemas import DenialAnalysis

_SYSTEM_PROMPT = """\
You are a healthcare prior-authorization specialist. Your job is to read
an insurer's denial letter and extract the structured facts a reviewer
will need to write an appeal.

You MUST follow these rules:

  - Every `quote` field must be a VERBATIM substring of the letter,
    copied character-for-character. Never paraphrase. Never summarize.
    Never add ellipsis. Never change punctuation.
  - Every `source_quote` entry must have a stable `quote_id` of the form
    "denial_qN" where N starts at 1 and increments.
  - Every `source_quote` must have `source_type = "denial_letter"`.
  - `quote_location` should be human-readable, e.g. "page 1, paragraph 2".
  - If the letter does not contain information for a requested field,
    use an empty list or null. Never fabricate content.
  - The `case_id` you output MUST match exactly the `case_id` in the
    user's request.

Return your answer by calling the emit_structured_output tool with a
valid DenialAnalysis object.
"""


def analyze_denial(case_id: str, denial_letter_path) -> DenialAnalysis:
    """Read the denial letter and return a verified structured analysis.

    Args:
        case_id: Stable ID for this case (e.g. "case_01_ozempic_bmi34").
            This value is echoed back into the DenialAnalysis so pipeline
            downstream stages can key off it.
        denial_letter_path: Path (or str) to the denial-letter PDF.

    Returns:
        A DenialAnalysis. Every SourceQuote it contains is intended to be
        a verbatim substring of the letter; the downstream Verifier will
        reject any citation whose quote cannot be found in the source.
    """
    image_blocks = render_pdf_to_image_blocks(Path(denial_letter_path))

    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Analyze the denial letter below for case_id='{case_id}'. "
                "Return the full structured DenialAnalysis object. "
                "Reminder: every quote must be VERBATIM from the letter."
            ),
        },
        *image_blocks,
    ]

    analysis, _raw = call_claude_structured(
        output_model=DenialAnalysis,
        system=cached_system(_SYSTEM_PROMPT),
        messages=[{"role": "user", "content": user_content}],
        max_tokens=4096,
    )
    return analysis
