"""
Orchestrator — runs the full appeal-generation pipeline.

Plain-language summary: the conductor. Takes the three input files
(denial letter, patient chart, payer policy), runs each specialist agent
in the right order, and passes each agent's output to the next. The last
step is always the Verifier, which guarantees no unverified claim ships.

Pipeline order:
    1. DenialAnalyzer   → what the insurer said
    2. PolicyReader     → what the insurer's policy requires
    3. ChartMiner       → what the patient's chart shows
    4. GuidelineCiter   → supporting professional-society guidelines
    5. LetterWriter     → first draft with citation markers
    6. Verifier         → re-checks every citation; strips unverifiable
"""
from __future__ import annotations

from auto_appeal_agent.agents.chart_miner import mine_chart
from auto_appeal_agent.agents.denial_analyzer import analyze_denial
from auto_appeal_agent.agents.guideline_citer import cite_guidelines
from auto_appeal_agent.agents.letter_writer import write_appeal
from auto_appeal_agent.agents.policy_reader import read_policy
from auto_appeal_agent.agents.verifier import verify_appeal
from auto_appeal_agent.schemas import PipelineInput, VerifiedAppeal


def run_pipeline(pipeline_input: PipelineInput) -> VerifiedAppeal:
    """Run every agent in order and return the final VerifiedAppeal."""
    denial = analyze_denial(pipeline_input.case_id, pipeline_input.denial_letter_path)
    policy = read_policy(pipeline_input.case_id, pipeline_input.payer_policy_path)
    evidence = mine_chart(
        pipeline_input.case_id,
        pipeline_input.patient_chart_path,
        policy.criteria,
    )
    _guidelines = cite_guidelines(
        pipeline_input.case_id,
        denial.denial_reasons,
        policy.criteria,
    )
    draft = write_appeal(
        pipeline_input.case_id, denial, policy, evidence, _guidelines
    )
    all_source_quotes = (
        denial.source_quotes + policy.source_quotes + evidence.source_quotes
    )
    return verify_appeal(draft, all_source_quotes)
