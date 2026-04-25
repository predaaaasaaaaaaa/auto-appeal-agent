"""
Tests for the local clinical-guideline corpus loader.

The corpus is the foundation for verifier-checked guideline citations:
if the loader is broken, every guideline citation in every appeal goes
unverified. These tests pin the contract: a populated corpus, well-
formed SourceQuotes, deterministic ordering, and stable quote_ids.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_appeal_agent.guideline_corpus import (
    GuidelineCorpus,
    GuidelineDoc,
    GuidelineExcerpt,
    corpus_source_quotes,
    format_corpus_for_prompt,
    load_corpus,
)


def test_shipped_corpus_loads():
    """The corpus.json under fixtures/guidelines/ must parse."""
    corpus = load_corpus()
    assert isinstance(corpus, GuidelineCorpus)
    assert len(corpus.guidelines) >= 5, "expect at least one guideline per case"


def test_every_guideline_has_at_least_one_excerpt():
    """A guideline with no excerpts contributes nothing to the Verifier."""
    corpus = load_corpus()
    for g in corpus.guidelines:
        assert g.excerpts, f"guideline {g.id} has no excerpts"


def test_excerpt_quote_ids_are_unique():
    """quote_id collisions would corrupt Verifier source_quote lookup."""
    corpus = load_corpus()
    seen: set[str] = set()
    for g in corpus.guidelines:
        for e in g.excerpts:
            assert e.quote_id not in seen, f"duplicate quote_id: {e.quote_id}"
            seen.add(e.quote_id)


def test_excerpt_quote_ids_have_guideline_prefix():
    """Stable convention: every guideline quote_id starts 'guideline_'."""
    corpus = load_corpus()
    for g in corpus.guidelines:
        for e in g.excerpts:
            assert e.quote_id.startswith("guideline_"), (
                f"non-conformant id: {e.quote_id}"
            )


def test_corpus_source_quotes_returns_one_per_excerpt():
    """One excerpt -> one SourceQuote, with clinical_guideline source_type."""
    corpus = load_corpus()
    expected = sum(len(g.excerpts) for g in corpus.guidelines)
    sqs = corpus_source_quotes(corpus)
    assert len(sqs) == expected
    assert all(sq.source_type == "clinical_guideline" for sq in sqs)


def test_corpus_source_quote_text_matches_excerpt_text():
    """Verifier substring-matches against SourceQuote.quote, so the text
    in the SourceQuote must be byte-identical to the excerpt text."""
    corpus = load_corpus()
    text_by_id = {e.quote_id: e.text for g in corpus.guidelines for e in g.excerpts}
    for sq in corpus_source_quotes(corpus):
        assert sq.quote == text_by_id[sq.quote_id]


def test_format_corpus_for_prompt_includes_every_excerpt():
    """The prompt formatter must emit every quote_id and every excerpt
    text, otherwise Claude can't cite excerpts the formatter missed."""
    corpus = load_corpus()
    formatted = format_corpus_for_prompt(corpus)
    for g in corpus.guidelines:
        assert g.id in formatted
        for e in g.excerpts:
            assert e.quote_id in formatted
            assert e.text in formatted


def test_load_corpus_accepts_custom_path(tmp_path: Path):
    """Tests can point the loader at a smaller fixture corpus."""
    mini = {
        "guidelines": [
            {
                "id": "demo_2026",
                "society": "Demo Society",
                "title": "Demo Guideline",
                "year": 2026,
                "url": None,
                "topics": ["demo"],
                "excerpts": [
                    {
                        "quote_id": "guideline_demo_2026_q1",
                        "section": "Demo section",
                        "text": "Demo text.",
                    }
                ],
            }
        ]
    }
    corpus_path = tmp_path / "mini.json"
    corpus_path.write_text(json.dumps(mini))
    # bypass the @lru_cache by passing the path directly
    load_corpus.cache_clear()
    corpus = load_corpus(corpus_path)
    assert len(corpus.guidelines) == 1
    assert corpus.guidelines[0].id == "demo_2026"
    load_corpus.cache_clear()


def test_excerpt_validates_extra_field_rejection():
    """The pydantic model is strict — unknown fields raise."""
    with pytest.raises(Exception):
        GuidelineExcerpt(
            quote_id="x", section="s", text="t", _extra="bad"
        )  # type: ignore[call-arg]


def test_guidelinedoc_round_trip():
    """Round-trip serialization preserves every field."""
    g = GuidelineDoc(
        id="x_2026",
        society="X",
        title="T",
        year=2026,
        url="http://e.com",
        topics=["a", "b"],
        excerpts=[GuidelineExcerpt(quote_id="guideline_x_2026_q1", section="s", text="t")],
    )
    again = GuidelineDoc.model_validate(g.model_dump())
    assert again == g
