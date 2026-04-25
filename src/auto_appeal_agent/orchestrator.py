"""
Orchestrator — runs the full appeal-generation pipeline.

Plain-language summary: the conductor. Takes the three input files
(denial letter, patient chart, payer policy), runs each specialist
agent in the right order, and passes each agent's output to the next.
The last step is always the Verifier, which guarantees no unverified
claim ships.

Pipeline order:
    1. DenialAnalyzer   → what the insurer said
    2. PolicyReader     → what the insurer's policy requires
    3. ChartMiner       → what the patient's chart shows
    4. GuidelineCiter   → supporting professional-society guidelines
    5. LetterWriter     → first draft with citation markers
    6. Verifier         → re-checks every citation; strips unverifiable

Optional progress_callback lets UI layers stream stage-by-stage updates
without needing to refactor the pipeline into a generator.

Cooperative cancellation: pass a `threading.Event` as `cancel_event`
to allow the caller (typically the SSE handler whose client just
disconnected) to abort the pipeline at the next agent boundary. The
in-flight Claude call CANNOT be interrupted (we cannot kill an
HTTP request mid-flight from another thread), but every later agent
will be skipped — capping worst-case wasted spend at one agent.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

from auto_appeal_agent.agents.chart_miner import mine_chart
from auto_appeal_agent.agents.denial_analyzer import analyze_denial
from auto_appeal_agent.agents.guideline_citer import cite_guidelines
from auto_appeal_agent.agents.independent_reviewer import independent_review
from auto_appeal_agent.agents.letter_writer import write_appeal
from auto_appeal_agent.agents.policy_reader import read_policy
from auto_appeal_agent.agents.verifier import verify_appeal
from auto_appeal_agent.schemas import PipelineInput, VerifiedAppeal

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]


class PipelineCancelled(Exception):
    """Raised when the supplied cancel_event is set between agents.

    Callers should catch this as a non-error termination — the user
    asked to stop, no failure happened. The API layer treats it
    that way (no spurious "pipeline error" emitted to a gone client).
    """


def _check_cancel(cancel_event: Optional[threading.Event]) -> None:
    """Raise PipelineCancelled if the caller has requested abort.

    Called between every agent so a Cancel click costs at most one
    in-flight Claude call.
    """
    if cancel_event is not None and cancel_event.is_set():
        raise PipelineCancelled("client disconnected mid-pipeline")


def _emit(cb: Optional[ProgressCallback], stage: str, status: str, **extra: Any) -> None:
    if cb is not None:
        # INFO log every emitted event so the API server log shows
        # exactly when each SSE frame is pushed onto the wire — useful
        # when diagnosing UI / browser timing issues against
        # backend-side reality.
        logger.info("emit_event stage=%s status=%s", stage, status)
        cb({"stage": stage, "status": status, **extra})


def run_pipeline(
    pipeline_input: PipelineInput,
    progress_callback: Optional[ProgressCallback] = None,
    second_pass: bool = False,
    cancel_event: Optional[threading.Event] = None,
) -> VerifiedAppeal:
    """Run every agent in order and return the final VerifiedAppeal.

    Args:
        pipeline_input: The three input file paths + case_id.
        progress_callback: Optional. If provided, called after every
            stage with a dict like
            `{"stage": "denial_analyzer", "status": "done", ...}`.
            Used by the UI layer to stream live progress.
        second_pass: When True, ALSO runs the IndependentReviewer after
            the substring Verifier and attaches its review to the
            returned VerifiedAppeal.second_pass_review. Defaults to
            False because the reviewer currently struggles on
            larger-than-fixture drafts; if it fails, the rest of the
            appeal is still returned and the review is omitted.
        cancel_event: Optional threading.Event. When set by the
            caller (e.g. the SSE handler in api/main.py noticing
            client disconnect), the pipeline raises PipelineCancelled
            at the next agent boundary, capping worst-case spend at
            one in-flight Claude call.
    """
    cb = progress_callback

    _check_cancel(cancel_event)
    _emit(cb, "denial_analyzer", "running")
    denial = analyze_denial(pipeline_input.case_id, pipeline_input.denial_letter_path)
    _emit(
        cb,
        "denial_analyzer",
        "done",
        denial_reasons=len(denial.denial_reasons),
        source_quotes=len(denial.source_quotes),
    )

    _check_cancel(cancel_event)
    _emit(cb, "policy_reader", "running")
    policy = read_policy(pipeline_input.case_id, pipeline_input.payer_policy_path)
    _emit(
        cb,
        "policy_reader",
        "done",
        criteria=len(policy.criteria),
        source_quotes=len(policy.source_quotes),
    )

    _check_cancel(cancel_event)
    _emit(cb, "chart_miner", "running")
    evidence = mine_chart(
        pipeline_input.case_id,
        pipeline_input.patient_chart_path,
        policy.criteria,
    )
    _emit(
        cb,
        "chart_miner",
        "done",
        evidence_items=len(evidence.evidence_items),
        source_quotes=len(evidence.source_quotes),
    )

    _check_cancel(cancel_event)
    _emit(cb, "guideline_citer", "running")
    guidelines = cite_guidelines(
        pipeline_input.case_id,
        denial.denial_reasons,
        policy.criteria,
    )
    _emit(cb, "guideline_citer", "done", citations=len(guidelines.citations))

    _check_cancel(cancel_event)
    _emit(cb, "letter_writer", "running")
    draft = write_appeal(
        pipeline_input.case_id, denial, policy, evidence, guidelines
    )
    total_citations = sum(len(p.citations) for p in draft.paragraphs)
    _emit(
        cb,
        "letter_writer",
        "done",
        paragraphs=len(draft.paragraphs),
        citations=total_citations,
    )

    _check_cancel(cancel_event)
    _emit(cb, "verifier", "running")
    # Guideline source_quotes are corpus-backed and now first-class
    # verifiable: any CitationMarker the LetterWriter emitted with a
    # guideline_<...> source_id is substring-checked here, exactly
    # like denial/policy/chart citations.
    all_source_quotes = (
        denial.source_quotes
        + policy.source_quotes
        + evidence.source_quotes
        + guidelines.source_quotes
    )
    verified = verify_appeal(draft, all_source_quotes)
    _emit(
        cb,
        "verifier",
        "done",
        verified_citations=len(verified.verified_citations),
        rejected_citations=len(verified.rejected_citations),
        pass_rate=verified.verification_pass_rate,
        ready_to_send=verified.ready_to_send,
    )

    if second_pass:
        _check_cancel(cancel_event)
        _emit(cb, "independent_reviewer", "running")
        try:
            review = independent_review(draft, all_source_quotes)
            verified.second_pass_review = review
            _emit(
                cb,
                "independent_reviewer",
                "done",
                overall_verdict=review.overall_verdict,
                citation_verdicts=len(review.citation_verdicts),
                high_level_concerns=len(review.high_level_concerns),
            )
        except Exception as exc:
            # The IndependentReviewer is a *bonus* QA layer on top of the
            # substring Verifier. If it fails (bad schema output, timeout,
            # rate limit), the core appeal is still valid — we return it
            # without the review rather than failing the whole pipeline.
            logger.warning(
                "IndependentReviewer failed; returning appeal without review: "
                "%s: %s",
                type(exc).__name__,
                exc,
            )
            _emit(
                cb,
                "independent_reviewer",
                "done",
                skipped=True,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

    return verified
