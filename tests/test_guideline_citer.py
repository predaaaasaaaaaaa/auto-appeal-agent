"""
GuidelineCiter integration tests.

Shape-only checks — we cannot verify guideline quotes against a local
source document (by design: GuidelineCiter uses Claude's training
knowledge, not the payer policy). The downstream LetterWriter uses
these citations as prose support only, never as verifiable
CitationMarkers.
"""
from __future__ import annotations

import pytest

from auto_appeal_agent.agents.guideline_citer import cite_guidelines
from auto_appeal_agent.schemas import DenialReason, MedicalNecessityCriterion


@pytest.mark.integration
def test_guideline_citer_returns_structured_output():
    denial_reasons = [
        DenialReason(
            reason="Not medically necessary; member does not meet criteria "
                   "for GLP-1 receptor agonist therapy",
            code="MN-12",
            quote="not medically necessary",
            quote_location="page 1",
        )
    ]
    criteria = [
        MedicalNecessityCriterion(
            criterion_id="mn_1",
            text="BMI at or above 30",
            quote="BMI at or above 30 kg/m^2",
            quote_location="section 2",
            category="diagnostics",
        ),
        MedicalNecessityCriterion(
            criterion_id="mn_2",
            text="Documented 6 months of supervised diet and exercise",
            quote="supervised program... for a minimum of six months",
            quote_location="section 2",
            category="prior_treatments",
        ),
    ]

    result = cite_guidelines(
        "case_01_ozempic_bmi34",
        denial_reasons,
        criteria,
    )

    assert result.case_id == "case_01_ozempic_bmi34"
    assert 1 <= len(result.citations) <= 4, (
        f"expected 1-4 citations, got {len(result.citations)}"
    )

    # Each citation must have non-empty required fields.
    for c in result.citations:
        assert c.citation_id.startswith("guideline_q")
        assert c.guideline_source, f"empty guideline_source on {c.citation_id}"
        # citation_title is optional; if present, must be non-empty.
        assert c.citation_title is None or c.citation_title.strip(), (
            f"blank citation_title on {c.citation_id}"
        )
        assert c.quote, f"empty quote on {c.citation_id}"
        assert c.supports_claim, f"empty supports_claim on {c.citation_id}"

    # citation_ids must be unique
    ids = [c.citation_id for c in result.citations]
    assert len(set(ids)) == len(ids), f"duplicate citation_ids: {ids}"

    # At least one citation should plausibly come from a diabetes/obesity
    # society given this is a GLP-1 appeal; cheap sanity check on relevance.
    bodies = " ".join(c.guideline_source for c in result.citations).lower()
    diabetes_bodies = ("ada", "american diabetes", "endocrine", "obesity")
    assert any(b in bodies for b in diabetes_bodies), (
        f"none of the citations came from an expected body; got: {bodies}"
    )
