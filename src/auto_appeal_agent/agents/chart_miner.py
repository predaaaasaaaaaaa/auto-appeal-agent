"""
ChartMiner — finds evidence in the patient's chart.

Plain-language summary: the patient's chart (their medical record) is the
raw evidence. For each criterion the policy requires, this agent searches
the chart for matching findings (a lab value, a past diagnosis, a note
from a prior visit, etc.) and records the exact quote so the Verifier
can later double-check it.

Phase 0 status: STUBBED. Phase 1 replaces with a real Claude call that
loads the whole chart in 1M-token context and mines for evidence.
"""
from __future__ import annotations

from pathlib import Path

from auto_appeal_agent.schemas import (
    ChartEvidence,
    EvidenceItem,
    MedicalNecessityCriterion,
    SourceQuote,
)


def mine_chart(
    case_id: str,
    patient_chart_path: Path,
    criteria: list[MedicalNecessityCriterion],
) -> ChartEvidence:
    """Return evidence items from the chart that match each criterion.

    Args:
        case_id: Stable ID for this case.
        patient_chart_path: Path to the patient's chart file.
        criteria: Criteria extracted by the PolicyReader; each one needs
            to be either supported or refuted by chart evidence.

    Returns:
        A ChartEvidence with placeholder content; shape is valid.
    """
    del patient_chart_path, criteria  # stub does not read the file yet
    return ChartEvidence(
        case_id=case_id,
        evidence_items=[
            EvidenceItem(
                criterion_id="mn_1",
                finding="[stub] BMI 34.2 recorded at 2026-03-12 visit",
                quote="[stub] BMI 34.2",
                quote_location="[stub] 2026-03-12 visit",
                supports_appeal=True,
            )
        ],
        criteria_met={"mn_1": True},
        source_quotes=[
            SourceQuote(
                quote_id="chart_q1",
                source_type="patient_chart",
                quote="[stub] BMI 34.2",
                location="[stub] 2026-03-12 visit",
            )
        ],
    )
