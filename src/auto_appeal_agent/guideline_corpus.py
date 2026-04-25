"""
Guideline corpus loader — turns the on-disk corpus.json into typed records
plus ready-made SourceQuote objects for the Verifier.

Plain-language summary: in V1 (this file), GuidelineCiter draws from a
small fixed corpus of professional-society clinical-guideline excerpts
shipped under fixtures/guidelines/. Each excerpt has a stable quote_id;
when the LetterWriter cites a guideline, it cites that quote_id, and
the Verifier substring-matches the cited verbatim_quote against the
excerpt text — exactly the same reliability primitive used for chart,
denial-letter, and policy citations.

Why this matters: before this corpus existed, GuidelineCiter generated
guideline references from Claude's training, with no way for the
Verifier to detect a hallucinated citation. With the corpus in place,
guideline citations sit on the same trust foundation as everything
else: "if it's in the appeal, the Verifier confirmed the verbatim
quote appears in a real source document".

Production note: the shipped corpus paraphrases real published
recommendations. A real deployment should swap in licensed verbatim
text from the original guideline PDFs (UpToDate, the society's open-
access publication, or a licensed vendor). This module's interface
does not change when that swap happens.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from auto_appeal_agent.schemas import SourceQuote


_CORPUS_PATH = (
    Path(__file__).resolve().parents[2] / "fixtures" / "guidelines" / "corpus.json"
)


class GuidelineExcerpt(BaseModel):
    """One quotable passage from a guideline document."""

    model_config = ConfigDict(extra="forbid")
    quote_id: str = Field(..., description="Stable id, e.g. 'guideline_acr_ra_2021_q1'.")
    section: str
    text: str


class GuidelineDoc(BaseModel):
    """One professional-society guideline document."""

    model_config = ConfigDict(extra="forbid")
    id: str
    society: str
    title: str
    year: int
    url: Optional[str] = None
    topics: list[str] = Field(default_factory=list)
    excerpts: list[GuidelineExcerpt]


class GuidelineCorpus(BaseModel):
    """The full corpus."""

    model_config = ConfigDict(extra="ignore")
    guidelines: list[GuidelineDoc]


@lru_cache(maxsize=1)
def load_corpus(corpus_path: Optional[Path] = None) -> GuidelineCorpus:
    """Load the corpus once and cache it.

    Args:
        corpus_path: Override for tests. Defaults to the shipped
            fixtures/guidelines/corpus.json.
    """
    path = corpus_path if corpus_path is not None else _CORPUS_PATH
    raw = json.loads(path.read_text(encoding="utf-8"))
    return GuidelineCorpus.model_validate(raw)


def corpus_source_quotes(corpus: Optional[GuidelineCorpus] = None) -> list[SourceQuote]:
    """Return every excerpt in the corpus as a SourceQuote ready for the Verifier.

    Each excerpt becomes a SourceQuote with source_type='clinical_guideline',
    quote_id from the corpus, location set to 'society + year + section',
    and quote text equal to the excerpt's text. The Verifier substring-
    matches CitationMarker.verbatim_quote against quote — exactly like the
    other source types.
    """
    c = corpus if corpus is not None else load_corpus()
    quotes: list[SourceQuote] = []
    for guideline in c.guidelines:
        for excerpt in guideline.excerpts:
            quotes.append(
                SourceQuote(
                    quote_id=excerpt.quote_id,
                    source_type="clinical_guideline",
                    quote=excerpt.text,
                    location=f"{guideline.society} {guideline.year} — {excerpt.section}",
                )
            )
    return quotes


def format_corpus_for_prompt(corpus: Optional[GuidelineCorpus] = None) -> str:
    """Render the corpus as plain text for the GuidelineCiter prompt.

    The model needs to see (a) every excerpt's quote_id, (b) the society
    and year, (c) the verbatim text it must quote from. This format is
    short, scannable, and unambiguous about which id maps to which text.
    """
    c = corpus if corpus is not None else load_corpus()
    lines: list[str] = []
    for guideline in c.guidelines:
        lines.append(
            f"## {guideline.id} — {guideline.society} ({guideline.year})"
        )
        lines.append(f"Title: {guideline.title}")
        if guideline.url:
            lines.append(f"URL: {guideline.url}")
        if guideline.topics:
            lines.append(f"Topics: {', '.join(guideline.topics)}")
        for excerpt in guideline.excerpts:
            lines.append("")
            lines.append(f"Excerpt id: {excerpt.quote_id}")
            lines.append(f"Section: {excerpt.section}")
            lines.append(f"Text: {excerpt.text}")
        lines.append("")
    return "\n".join(lines)
