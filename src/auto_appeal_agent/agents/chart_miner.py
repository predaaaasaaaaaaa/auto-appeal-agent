"""
ChartMiner — searches the patient's chart for evidence matching each
criterion the PolicyReader extracted.

For every criterion the payer requires, the ChartMiner hunts through the
chart for a finding that either supports or refutes it, and records the
verbatim chart excerpt that backs the finding.

This agent is the one place the pipeline needs clinical judgment — does
"BMI 34.2" count as meeting "BMI >= 30"? Does "attended 21 of 24
sessions" count as "documented compliance"? We enable Claude 4.7's
adaptive thinking for this reason: a couple of internal reasoning
tokens per criterion is well worth the accuracy gain.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from auto_appeal_agent.anthropic_client import call_claude_structured
from auto_appeal_agent.schemas import ChartEvidence, MedicalNecessityCriterion

_SYSTEM_PROMPT = """\
You are a healthcare clinical data abstractor. Your job is to search a
patient's chart for evidence supporting each of the criteria the payer's
medical policy requires.

You MUST follow these rules:

  - For EACH criterion the user gives you, look for evidence in the
    chart that either supports or refutes that criterion.
  - Record the VERBATIM quote from the chart that establishes each
    finding, character-for-character. Never paraphrase.
  - Every `source_quote` has `source_type = "patient_chart"` and a
    unique `quote_id` of the form "chart_qN".
  - Every `evidence_item.criterion_id` must match one of the
    criterion_ids in the user's input list. Do not invent new ones.
  - `supports_appeal = True` when the evidence helps the patient meet
    the criterion; False when it refutes it.
  - `criteria_met` maps criterion_id -> True if the patient meets that
    criterion per your evidence, False if the chart refutes it. If the
    chart is silent on a criterion, OMIT it from criteria_met rather
    than guessing.
  - If the chart has no evidence for a criterion, do not fabricate one.
    Simply skip it.
  - The `case_id` in your output MUST match the user's case_id.

Return your answer by calling the emit_structured_output tool with a
valid ChartEvidence object.
"""


def _format_criteria(criteria: list[MedicalNecessityCriterion]) -> str:
    lines = []
    for c in criteria:
        lines.append(
            f"  - criterion_id={c.criterion_id}  "
            f"category={c.category}\n"
            f"    text: {c.text}\n"
            f"    policy_quote: {c.quote!r}"
        )
    return "\n".join(lines)


def mine_chart(
    case_id: str,
    patient_chart_path,
    criteria: list[MedicalNecessityCriterion],
) -> ChartEvidence:
    """Find verbatim chart evidence for each policy criterion.

    Args:
        case_id: Stable case ID.
        patient_chart_path: Path to the patient-chart text file.
        criteria: Criteria from the PolicyReader; only these criterion_ids
            may appear in the output.

    Returns:
        A ChartEvidence whose source quotes are intended to be verbatim
        substrings of the chart text.
    """
    chart_text = Path(patient_chart_path).read_text(encoding="utf-8")

    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Search the patient chart for evidence matching the policy "
                f"criteria below. case_id='{case_id}'.\n\n"
                f"CRITERIA:\n{_format_criteria(criteria)}\n\n"
                f"PATIENT CHART:\n{chart_text}"
            ),
        }
    ]

    evidence, _raw = call_claude_structured(
        output_model=ChartEvidence,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
        max_tokens=8192,
        thinking=True,
    )
    return evidence
