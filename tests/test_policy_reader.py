"""
PolicyReader integration tests.

Runs the real agent against fixture case 01 (BlueSun GLP-1 policy) and
verifies that it extracts sensible criteria with verbatim source quotes.

Marked @pytest.mark.integration; only runs with `make test-integration`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from auto_appeal_agent.agents.policy_reader import read_policy
from auto_appeal_agent.pdf_utils import extract_text


def _normalize(s: str) -> str:
    return " ".join(s.lower().split())


def test_policy_reader_extracts_case_01(cassette, fixtures_dir: Path):  # noqa: ARG001
    case_dir = fixtures_dir / "case_01_ozempic_bmi34"
    policy = read_policy(
        "case_01_ozempic_bmi34",
        case_dir / "payer_policy.pdf",
    )

    # Shape
    assert policy.case_id == "case_01_ozempic_bmi34"

    # Policy name should match what's in the document.
    assert "glp-1" in policy.policy_name.lower() or "medpol-glp1" in policy.policy_name.lower()

    # The BlueSun GLP-1 policy lists four main criteria (age, BMI,
    # supervised program, contraindications) plus a step-therapy
    # requirement. Extractor should surface at least four of those five.
    assert len(policy.criteria) >= 4, (
        f"expected at least 4 criteria, got {len(policy.criteria)}"
    )

    # Every source quote must be typed correctly.
    assert all(sq.source_type == "payer_policy" for sq in policy.source_quotes)

    # Every criterion_id must be unique and well-formed.
    ids = [c.criterion_id for c in policy.criteria]
    assert len(set(ids)) == len(ids), f"duplicate criterion_ids: {ids}"

    # Every source_quote_id must be unique and well-formed.
    sq_ids = [sq.quote_id for sq in policy.source_quotes]
    assert len(set(sq_ids)) == len(sq_ids), f"duplicate quote_ids: {sq_ids}"

    # Reliability gate: every source quote and every criterion quote
    # must appear in the policy's text (normalized substring).
    policy_text = _normalize(extract_text(case_dir / "payer_policy.pdf"))

    unverified_sq = [
        sq for sq in policy.source_quotes
        if _normalize(sq.quote) not in policy_text
    ]
    assert not unverified_sq, (
        "Source quotes not found verbatim in the policy:\n"
        + "\n".join(f"  - {sq.quote_id}: {sq.quote!r}" for sq in unverified_sq)
    )

    unverified_crit = [
        c for c in policy.criteria
        if _normalize(c.quote) not in policy_text
    ]
    assert not unverified_crit, (
        "Criterion quotes not found verbatim in the policy:\n"
        + "\n".join(f"  - {c.criterion_id}: {c.quote!r}" for c in unverified_crit)
    )


def test_policy_reader_categories_are_valid(cassette, fixtures_dir: Path):  # noqa: ARG001
    """Sanity: categories must be one of the allowed EvidenceCategory values."""
    allowed = {
        "clinical_history",
        "diagnostics",
        "prior_treatments",
        "functional_status",
        "contraindications",
        "other",
    }
    policy = read_policy(
        "case_01_ozempic_bmi34",
        fixtures_dir / "case_01_ozempic_bmi34" / "payer_policy.pdf",
    )
    for c in policy.criteria:
        assert c.category in allowed, f"unexpected category: {c.category}"
