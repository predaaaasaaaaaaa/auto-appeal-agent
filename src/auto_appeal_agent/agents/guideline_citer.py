"""
GuidelineCiter — finds supporting clinical-society guidelines.

Plain-language summary: professional medical societies (American Diabetes
Association, American College of Cardiology, etc.) publish clinical
guidelines telling doctors what the standard of care is. When we appeal,
citing these guidelines strengthens our case. This agent finds guidelines
that support the treatment being appealed.

Phase 0 status: STUBBED. Phase 1 will likely use the Anthropic web-search
or a curated local corpus of guideline PDFs.
"""
from __future__ import annotations

from auto_appeal_agent.schemas import (
    DenialReason,
    GuidelineCitation,
    GuidelineCitations,
    MedicalNecessityCriterion,
)


def cite_guidelines(
    case_id: str,
    denial_reasons: list[DenialReason],
    criteria: list[MedicalNecessityCriterion],
) -> GuidelineCitations:
    """Return a set of clinical-guideline citations that support the appeal.

    Args:
        case_id: Stable ID for this case.
        denial_reasons: Reasons the insurer gave; guidelines should
            counter these directly.
        criteria: Policy criteria; guidelines should support that the
            patient's situation matches these criteria.

    Returns:
        A GuidelineCitations with placeholder content; shape is valid.
    """
    del denial_reasons, criteria  # stub does not consult sources yet
    return GuidelineCitations(
        case_id=case_id,
        citations=[
            GuidelineCitation(
                citation_id="g1",
                guideline_source="[stub] ADA 2024 Standards of Care",
                citation_title="[stub] Pharmacologic Therapy for Obesity",
                quote="[stub] GLP-1 RAs are recommended for adults with BMI >= 30",
                url=None,
                supports_claim="[stub] BMI >= 30 qualifies the patient for GLP-1 therapy",
            )
        ],
    )
