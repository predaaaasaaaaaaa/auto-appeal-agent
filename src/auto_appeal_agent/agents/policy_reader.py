"""
PolicyReader — reads the insurance plan's medical policy.

Plain-language summary: every insurer publishes "medical policies" that
list the exact conditions a patient must meet for a given treatment to be
covered (e.g. "GLP-1 agonists require BMI >= 30 and prior failure of diet
and exercise"). This module reads one of those policy documents and
extracts those conditions as a structured list of criteria.

Phase 0 status: STUBBED. Phase 1 replaces with a real Claude call that
reads the payer-policy PDF and emits the criteria the patient must meet.
"""
from __future__ import annotations

from pathlib import Path

from auto_appeal_agent.schemas import (
    MedicalNecessityCriterion,
    PolicyCriteria,
    SourceQuote,
)


def read_policy(case_id: str, payer_policy_path: Path) -> PolicyCriteria:
    """Return the structured criteria the patient must meet for coverage.

    Args:
        case_id: Stable ID for this case.
        payer_policy_path: Path to the payer's medical-policy PDF.

    Returns:
        A PolicyCriteria with placeholder content; shape is valid.
    """
    del payer_policy_path  # stub does not read the file yet
    return PolicyCriteria(
        case_id=case_id,
        policy_name="[stub] ACME GLP-1 Policy v3",
        policy_effective_date="2026-01-01",
        criteria=[
            MedicalNecessityCriterion(
                criterion_id="mn_1",
                text="[stub] BMI greater than or equal to 30",
                quote="[stub] BMI >= 30",
                quote_location="[stub] section 2",
                category="diagnostics",
            )
        ],
        source_quotes=[
            SourceQuote(
                quote_id="policy_q1",
                source_type="payer_policy",
                quote="[stub] BMI >= 30",
                location="[stub] section 2",
            )
        ],
    )
