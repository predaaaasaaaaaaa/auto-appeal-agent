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
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from auto_appeal_agent.agents.chart_miner import mine_chart
from auto_appeal_agent.agents.denial_analyzer import analyze_denial
from auto_appeal_agent.agents.guideline_citer import cite_guidelines
from auto_appeal_agent.agents.letter_writer import write_appeal
from auto_appeal_agent.agents.policy_reader import read_policy
from auto_appeal_agent.agents.verifier import verify_appeal
from auto_appeal_agent.schemas import PipelineInput, VerifiedAppeal

ProgressCallback = Callable[[dict[str, Any]], None]


def _emit(cb: Optional[ProgressCallback], stage: str, status: str, **extra: Any) -> None:
    if cb is not None:
        cb({"stage": stage, "status": status, **extra})


def run_pipeline(
    pipeline_input: PipelineInput,
    progress_callback: Optional[ProgressCallback] = None,
) -> VerifiedAppeal:
    """Run every agent in order and return the final VerifiedAppeal.

    Args:
        pipeline_input: The three input file paths + case_id.
        progress_callback: Optional. If provided, called after every
            stage with a dict like
            `{"stage": "denial_analyzer", "status": "done", ...}`.
            Used by the UI layer to stream live progress.
    """
    cb = progress_callback

    _emit(cb, "denial_analyzer", "running")
    denial = analyze_denial(pipeline_input.case_id, pipeline_input.denial_letter_path)
    _emit(
        cb,
        "denial_analyzer",
        "done",
        denial_reasons=len(denial.denial_reasons),
        source_quotes=len(denial.source_quotes),
    )

    _emit(cb, "policy_reader", "running")
    policy = read_policy(pipeline_input.case_id, pipeline_input.payer_policy_path)
    _emit(
        cb,
        "policy_reader",
        "done",
        criteria=len(policy.criteria),
        source_quotes=len(policy.source_quotes),
    )

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

    _emit(cb, "guideline_citer", "running")
    guidelines = cite_guidelines(
        pipeline_input.case_id,
        denial.denial_reasons,
        policy.criteria,
    )
    _emit(cb, "guideline_citer", "done", citations=len(guidelines.citations))

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

    _emit(cb, "verifier", "running")
    all_source_quotes = (
        denial.source_quotes + policy.source_quotes + evidence.source_quotes
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

    return verified
