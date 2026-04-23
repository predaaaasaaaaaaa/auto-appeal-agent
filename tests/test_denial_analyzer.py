"""
DenialAnalyzer integration tests.

Runs the real agent against fixture case 01 (Ozempic denial) and verifies:
  * output shape,
  * core fields are populated from the letter (not hallucinated),
  * every source quote is actually present in the letter's text
    (verbatim-reliability gate).

Marked @pytest.mark.integration — does not run with the default pytest,
only with `pytest -m integration` or `make test-integration`.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from auto_appeal_agent.agents.denial_analyzer import analyze_denial


def _pdf_text(path: Path) -> str:
    doc = fitz.open(path)
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


def _normalize(s: str) -> str:
    """Case + whitespace normalization, matching the Verifier's leniency."""
    return " ".join(s.lower().split())


@pytest.mark.integration
def test_denial_analyzer_extracts_case_01(fixtures_dir: Path):
    case_dir = fixtures_dir / "case_01_ozempic_bmi34"
    analysis = analyze_denial(
        "case_01_ozempic_bmi34",
        case_dir / "denial_letter.pdf",
    )

    # Shape
    assert analysis.case_id == "case_01_ozempic_bmi34"

    # Member: letter names Jane A. Doe, BS-A1234567, BlueSun Health Premium HMO.
    name_l = analysis.member_info.member_name.lower()
    assert "jane" in name_l or "doe" in name_l, f"name not matched: {name_l}"
    assert "a1234567" in analysis.member_info.member_id.lower()
    assert "bluesun" in analysis.member_info.plan_name.lower()

    # Requested service: Ozempic / semaglutide
    svc_l = analysis.requested_service.lower()
    assert "ozempic" in svc_l or "semaglutide" in svc_l

    # At least one denial reason and one source quote
    assert len(analysis.denial_reasons) >= 1
    assert len(analysis.source_quotes) >= 1

    # Reliability gate: every source quote must appear in the letter
    # (normalized whitespace/case, matching the Verifier's behavior).
    letter_text = _normalize(_pdf_text(case_dir / "denial_letter.pdf"))
    unverified = [
        sq for sq in analysis.source_quotes
        if _normalize(sq.quote) not in letter_text
    ]
    assert not unverified, (
        "Non-verbatim source quotes (Claude hallucinated or paraphrased):\n"
        + "\n".join(f"  - {sq.quote_id}: {sq.quote!r}" for sq in unverified)
    )

    # Every source quote should be typed as denial_letter
    assert all(sq.source_type == "denial_letter" for sq in analysis.source_quotes)
    # quote_ids are unique
    ids = [sq.quote_id for sq in analysis.source_quotes]
    assert len(set(ids)) == len(ids), f"duplicate quote_ids: {ids}"
