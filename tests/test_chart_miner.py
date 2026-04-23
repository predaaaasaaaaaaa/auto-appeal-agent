"""
ChartMiner integration tests.

Uses hand-written criteria (not PolicyReader output) so this test only
exercises ChartMiner. Verifies:
  * core BMI / lifestyle-program evidence is found,
  * verbatim reliability (every quote is a chart substring),
  * evidence_items reference only input criterion_ids.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from auto_appeal_agent.agents.chart_miner import mine_chart
from auto_appeal_agent.schemas import MedicalNecessityCriterion


def _normalize(s: str) -> str:
    return " ".join(s.lower().split())


def _case_01_criteria() -> list[MedicalNecessityCriterion]:
    return [
        MedicalNecessityCriterion(
            criterion_id="mn_bmi",
            text="BMI at or above 30 kg/m^2",
            quote="Body Mass Index (BMI) at or above 30 kg/m^2",
            quote_location="criteria section",
            category="diagnostics",
        ),
        MedicalNecessityCriterion(
            criterion_id="mn_diet_exercise",
            text="At least six months of supervised diet, exercise, and behavior modification",
            quote=(
                "supervised program of reduced-calorie diet, increased "
                "physical activity, and behavior modification for a minimum "
                "of six months"
            ),
            quote_location="criteria section",
            category="prior_treatments",
        ),
        MedicalNecessityCriterion(
            criterion_id="mn_no_contra",
            text="No contraindications (MTC, MEN2, pregnancy)",
            quote=(
                "personal or family history of medullary thyroid carcinoma"
            ),
            quote_location="criteria section",
            category="contraindications",
        ),
    ]


def test_chart_miner_finds_case_01_evidence(cassette, fixtures_dir: Path):  # noqa: ARG001
    case_dir = fixtures_dir / "case_01_ozempic_bmi34"
    criteria = _case_01_criteria()

    evidence = mine_chart(
        "case_01_ozempic_bmi34",
        case_dir / "patient_chart.txt",
        criteria,
    )

    # Shape
    assert evidence.case_id == "case_01_ozempic_bmi34"
    assert len(evidence.evidence_items) >= 2, "expected evidence for at least 2 criteria"
    assert len(evidence.source_quotes) >= 2

    # All source_quotes typed correctly
    assert all(sq.source_type == "patient_chart" for sq in evidence.source_quotes)

    # evidence_items must only reference input criterion_ids
    allowed_ids = {c.criterion_id for c in criteria}
    invalid = [e for e in evidence.evidence_items if e.criterion_id not in allowed_ids]
    assert not invalid, f"evidence_items reference unknown criterion_ids: {invalid}"

    # BMI criterion should be met (chart has BMI 34.2)
    assert evidence.criteria_met.get("mn_bmi") is True, (
        f"expected BMI criterion met; criteria_met={evidence.criteria_met}"
    )
    # Diet/exercise criterion should be met (10 months of Weight Watchers)
    assert evidence.criteria_met.get("mn_diet_exercise") is True, (
        f"expected diet/exercise criterion met; criteria_met={evidence.criteria_met}"
    )

    # Verbatim-quote reliability
    chart_text = _normalize(
        (case_dir / "patient_chart.txt").read_text(encoding="utf-8")
    )
    unverified = [
        sq for sq in evidence.source_quotes
        if _normalize(sq.quote) not in chart_text
    ]
    assert not unverified, (
        "Source quotes not found verbatim in chart:\n"
        + "\n".join(f"  - {sq.quote_id}: {sq.quote!r}" for sq in unverified)
    )
