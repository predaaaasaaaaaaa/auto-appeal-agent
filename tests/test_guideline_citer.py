"""
GuidelineCiter integration tests.

V1.1 (2026-04-25): GuidelineCiter retrieves from a fixed local corpus
under fixtures/guidelines/, not from Claude's training. These tests
pin the corpus-backed contract:

  * Every citation_id IS a real corpus excerpt id.
  * Every quote IS the corpus excerpt's verbatim text (byte-for-byte).
  * source_quotes is populated with one SourceQuote per cited excerpt.
  * Every cited excerpt's SourceQuote.quote matches the citation's
    quote — so the downstream Verifier substring-check is guaranteed
    to pass for any CitationMarker the LetterWriter emits against it.
"""
from __future__ import annotations

from auto_appeal_agent.agents.guideline_citer import cite_guidelines
from auto_appeal_agent.guideline_corpus import load_corpus
from auto_appeal_agent.schemas import DenialReason, MedicalNecessityCriterion


def test_guideline_citer_returns_structured_output(cassette):  # noqa: ARG001
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

    # Build a quick lookup table of every excerpt the corpus exposes,
    # so we can assert citation IDs and quote text match the corpus
    # byte-for-byte (the contract that lets the Verifier work).
    corpus = load_corpus()
    excerpt_by_id = {
        e.quote_id: e for g in corpus.guidelines for e in g.excerpts
    }

    assert result.case_id == "case_01_ozempic_bmi34"
    assert 1 <= len(result.citations) <= 4, (
        f"expected 1-4 citations, got {len(result.citations)}"
    )

    for c in result.citations:
        # Corpus-backed contract: citation_id MUST be a known corpus
        # excerpt id, and the cited quote MUST be the corpus excerpt's
        # verbatim text.
        assert c.citation_id in excerpt_by_id, (
            f"citation_id {c.citation_id!r} is not a known corpus excerpt"
        )
        assert c.quote == excerpt_by_id[c.citation_id].text, (
            f"quote on {c.citation_id} does not match corpus excerpt text"
        )
        assert c.guideline_source, f"empty guideline_source on {c.citation_id}"
        assert c.citation_title is None or c.citation_title.strip(), (
            f"blank citation_title on {c.citation_id}"
        )
        assert c.supports_claim, f"empty supports_claim on {c.citation_id}"

    # citation_ids must be unique within the response.
    ids = [c.citation_id for c in result.citations]
    assert len(set(ids)) == len(ids), f"duplicate citation_ids: {ids}"

    # source_quotes must materialize one SourceQuote per cited excerpt,
    # and each must be substring-checkable against the citation's quote.
    cited_ids = set(ids)
    sq_ids = {sq.quote_id for sq in result.source_quotes}
    assert sq_ids == cited_ids, (
        f"source_quotes mismatch — cited {cited_ids}, materialized {sq_ids}"
    )
    for sq in result.source_quotes:
        assert sq.source_type == "clinical_guideline"
        assert sq.quote == excerpt_by_id[sq.quote_id].text

    # Sanity check: at least one citation should plausibly come from a
    # diabetes / obesity / GLP-1 society given this is a GLP-1 appeal.
    bodies = " ".join(c.guideline_source for c in result.citations).lower()
    diabetes_bodies = ("ada", "american diabetes", "endocrine", "obesity")
    assert any(b in bodies for b in diabetes_bodies), (
        f"none of the citations came from an expected body; got: {bodies}"
    )
