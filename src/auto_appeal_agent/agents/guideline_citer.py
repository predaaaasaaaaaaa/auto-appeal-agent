"""
GuidelineCiter — picks supporting clinical-guideline excerpts from the
LOCAL corpus that back the patient's appeal.

Reliability contract (V1.1, 2026-04-25):

  * Citations are no longer free-generated from Claude's training. The
    corpus under fixtures/guidelines/ is the closed universe of
    quotable text. Claude receives the full corpus in the prompt,
    picks 1-4 excerpts whose recommendations support the appeal, and
    emits citations whose `citation_id` exactly matches the
    corpus excerpt's quote_id and whose `quote` is the excerpt's
    verbatim text.
  * Each cited excerpt is also returned as a SourceQuote with
    source_type='clinical_guideline', so the Verifier substring-
    checks guideline CitationMarkers using the same primitive used
    for chart/denial/policy citations.

What this does NOT do: invent guidelines, paraphrase corpus text, or
cite anything not in the corpus. The strict tool-use schema plus the
Verifier's substring re-check make the pipeline immune to the model
slipping into free generation.

Production note: the shipped corpus paraphrases real recommendations.
Swap in licensed verbatim text from each guideline (UpToDate, the
society's open-access publication, or a licensed vendor) without
changing this module's interface.
"""
from __future__ import annotations

from typing import Any

from auto_appeal_agent.anthropic_client import call_claude_structured, cached_system
from auto_appeal_agent.prompt_safety import PROMPT_INJECTION_GUARDRAIL, wrap_data
from auto_appeal_agent.guideline_corpus import (
    GuidelineCorpus,
    corpus_source_quotes,
    format_corpus_for_prompt,
    load_corpus,
)
from auto_appeal_agent.schemas import (
    DenialReason,
    GuidelineCitations,
    MedicalNecessityCriterion,
    SourceQuote,
)

_SYSTEM_PROMPT = """\
You are a clinical-evidence specialist. Given a prior-authorization
denial and the payer's medical-necessity criteria, your job is to pick
1-4 excerpts from the LOCAL CLINICAL-GUIDELINE CORPUS the user provides
that support the patient's appeal.

Strict rules — every output is automatically verified:

  - Cite ONLY excerpts that appear in the supplied corpus. Do not
    invent excerpts, do not paraphrase, do not blend two excerpts.
  - Each citation's `citation_id` MUST be exactly the corpus excerpt's
    `Excerpt id` (e.g. "guideline_acr_ra_2021_q1"). No other format
    will be accepted.
  - Each citation's `quote` MUST be the verbatim excerpt text from
    the corpus, character for character. The Verifier substring-
    matches this against the corpus and rejects anything else.
  - `guideline_source` MUST match the society + year shown for the
    chosen excerpt in the corpus.
  - `citation_title` MUST match the guideline's `Title` field.
  - `url` MUST be the corpus's URL field for that guideline (or null
    if the corpus omits it).
  - `supports_claim` is your own one-line summary of which appeal claim
    this citation backs (e.g. "BMI >= 30 with comorbidity qualifies for
    GLP-1 pharmacotherapy"). Be specific.
  - Prefer the FEWEST citations needed. One on-point excerpt beats
    three loosely-related ones.

Return a valid GuidelineCitations object with `case_id` matching the
user's case_id, the citation list, and `source_quotes` empty (the
pipeline materializes SourceQuotes from your citation_ids).
""" + PROMPT_INJECTION_GUARDRAIL


def _format_denial_reasons(reasons: list[DenialReason]) -> str:
    return "\n".join(f"  - {r.reason}" for r in reasons)


def _format_criteria(criteria: list[MedicalNecessityCriterion]) -> str:
    return "\n".join(f"  - {c.text}" for c in criteria)


def cite_guidelines(
    case_id: str,
    denial_reasons: list[DenialReason],
    criteria: list[MedicalNecessityCriterion],
    corpus: GuidelineCorpus | None = None,
) -> GuidelineCitations:
    """Return corpus-backed guideline citations supporting the appeal.

    Args:
        case_id: Pipeline case id; round-tripped into the output.
        denial_reasons: From DenialAnalyzer; tells Claude what the
            insurer's stated objections are.
        criteria: From PolicyReader; tells Claude which medical-
            necessity criteria the appeal must support.
        corpus: Override for tests. Defaults to the shipped corpus.

    Returns:
        A GuidelineCitations with `citations` (each tied to a corpus
        excerpt) and `source_quotes` (every cited excerpt as a
        SourceQuote ready for the Verifier).
    """
    c = corpus if corpus is not None else load_corpus()
    corpus_text = format_corpus_for_prompt(c)

    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "LOCAL CLINICAL-GUIDELINE CORPUS — every excerpt below is the\n"
                "complete universe of quotable guideline text for this run.\n"
                "Cite excerpts BY ID with their VERBATIM text only.\n\n"
                # Corpus is shipped with this repo (NOT user-controlled),
                # but wrap it anyway so all data blocks have a uniform
                # shape and the model's "data vs. instructions" boundary
                # is consistent across agents.
                f"{wrap_data('guideline_corpus', corpus_text)}"
            ),
        },
        {
            "type": "text",
            "text": (
                f"Identify supporting guideline excerpts for case_id='{case_id}'.\n\n"
                f"{wrap_data('denial_reasons', _format_denial_reasons(denial_reasons))}\n\n"
                f"{wrap_data('policy_criteria', _format_criteria(criteria))}\n\n"
                "Return 1-4 high-confidence GuidelineCitations from the corpus."
            ),
        }
    ]

    citations, _raw = call_claude_structured(
        output_model=GuidelineCitations,
        system=cached_system(_SYSTEM_PROMPT),
        messages=[{"role": "user", "content": user_content}],
        max_tokens=2048,
    )

    # The model returns citations referencing corpus excerpts by
    # quote_id. We materialize the matching SourceQuotes here so
    # the Verifier can substring-check them. Doing this server-side
    # (instead of asking the model to echo the SourceQuotes) keeps
    # the corpus authoritative — the model can't accidentally
    # paraphrase a SourceQuote text it copied from the prompt.
    cited_ids = {citation.citation_id for citation in citations.citations}
    all_source_quotes = corpus_source_quotes(c)
    citations.source_quotes = [
        sq for sq in all_source_quotes if sq.quote_id in cited_ids
    ]
    return citations
