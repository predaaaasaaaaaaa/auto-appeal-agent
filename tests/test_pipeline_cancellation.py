"""
Pipeline cancellation tests — proves PipelineCancelled fires at agent
boundaries when cancel_event is set.

These are pure unit tests with mocked agent functions. No API calls,
no cassettes. They simulate the real-world flow:
  1. SSE handler creates a cancel_event.
  2. Client disconnects.
  3. Handler sets cancel_event in finally.
  4. Worker thread, between agents, sees the event and raises.
  5. Pipeline stops at the next agent boundary — capping wasted spend
     at one in-flight Claude call instead of running through all six.
"""
from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from auto_appeal_agent.orchestrator import (
    PipelineCancelled,
    _check_cancel,
    run_pipeline,
)
from auto_appeal_agent.schemas import (
    AppealDraft,
    AppealParagraph,
    ChartEvidence,
    CitationMarker,
    DenialAnalysis,
    DenialReason,
    EvidenceItem,
    GuidelineCitations,
    MedicalNecessityCriterion,
    MemberInfo,
    PipelineInput,
    PolicyCriteria,
    SourceQuote,
)


# ---------------------------------------------------------------------------
# _check_cancel — the single primitive that everything else builds on
# ---------------------------------------------------------------------------


def test_check_cancel_does_nothing_when_event_is_none():
    """The default cancel_event is None — pipelines that don't opt in
    must not raise."""
    _check_cancel(None)  # must not raise


def test_check_cancel_does_nothing_when_event_not_set():
    """Event present but not set — caller hasn't asked to cancel yet."""
    _check_cancel(threading.Event())  # must not raise


def test_check_cancel_raises_pipeline_cancelled_when_event_set():
    """Event set — caller asked to abort. Raise PipelineCancelled
    (not generic Exception, so the API layer can distinguish from
    real failures)."""
    ev = threading.Event()
    ev.set()
    with pytest.raises(PipelineCancelled):
        _check_cancel(ev)


# ---------------------------------------------------------------------------
# run_pipeline — cancellation between agents
# ---------------------------------------------------------------------------


# Hand-rolled stand-in agent outputs. Calling these is free and
# deterministic — they let us assert exactly which agents ran before
# the cancel kicked in.


def _stub_denial(case_id: str, _path: str) -> DenialAnalysis:
    return DenialAnalysis(
        case_id=case_id,
        member_info=MemberInfo(
            member_name="Test Patient",
            member_id="X1",
            plan_name="Test Plan",
        ),
        requested_service="test service",
        denial_reasons=[DenialReason(reason="r", quote="q", quote_location="loc")],
        source_quotes=[
            SourceQuote(
                quote_id="denial_q1",
                source_type="denial_letter",
                quote="q",
                location="loc",
            )
        ],
    )


def _stub_policy(case_id: str, _path: str) -> PolicyCriteria:
    return PolicyCriteria(
        case_id=case_id,
        policy_name="P",
        criteria=[
            MedicalNecessityCriterion(
                criterion_id="mn_1",
                text="t",
                quote="q",
                quote_location="loc",
                category="diagnostics",
            )
        ],
        source_quotes=[
            SourceQuote(
                quote_id="policy_q1",
                source_type="payer_policy",
                quote="q",
                location="loc",
            )
        ],
    )


def _stub_chart(case_id: str, _path: str, _criteria: list) -> ChartEvidence:
    return ChartEvidence(
        case_id=case_id,
        evidence_items=[
            EvidenceItem(
                criterion_id="mn_1",
                finding="f",
                quote="q",
                quote_location="loc",
                supports_appeal=True,
            )
        ],
        source_quotes=[
            SourceQuote(
                quote_id="chart_q1",
                source_type="patient_chart",
                quote="q",
                location="loc",
            )
        ],
    )


def _stub_guidelines(case_id: str, _denial, _criteria) -> GuidelineCitations:
    return GuidelineCitations(case_id=case_id, citations=[], source_quotes=[])


def _stub_letter(case_id: str, _denial, _policy, _evidence, _guidelines) -> AppealDraft:
    return AppealDraft(
        case_id=case_id,
        recipient_plan="Test Plan",
        subject_line="Subj",
        paragraphs=[
            AppealParagraph(
                text="x",
                citations=[
                    CitationMarker(
                        claim="c",
                        source_type="patient_chart",
                        source_id="chart_q1",
                        verbatim_quote="q",
                    )
                ],
            )
        ],
    )


@pytest.fixture
def stub_pipeline(monkeypatch):
    """Replace every agent with a hand-rolled stand-in.

    Tests can layer on top of this with `cancel_at_stage` to flip the
    cancel_event when a specific agent's stub runs, then assert the
    pipeline stopped at the right agent boundary.
    """
    monkeypatch.setattr(
        "auto_appeal_agent.orchestrator.analyze_denial", _stub_denial
    )
    monkeypatch.setattr("auto_appeal_agent.orchestrator.read_policy", _stub_policy)
    monkeypatch.setattr("auto_appeal_agent.orchestrator.mine_chart", _stub_chart)
    monkeypatch.setattr(
        "auto_appeal_agent.orchestrator.cite_guidelines", _stub_guidelines
    )
    monkeypatch.setattr("auto_appeal_agent.orchestrator.write_appeal", _stub_letter)


def _input() -> PipelineInput:
    return PipelineInput(
        case_id="case_test",
        denial_letter_path="x",
        patient_chart_path="x",
        payer_policy_path="x",
    )


def test_run_pipeline_succeeds_when_cancel_event_never_set(stub_pipeline):
    """Sanity: with stubs, a non-set cancel_event runs the full pipeline."""
    cancel_event = threading.Event()
    events: list[dict] = []
    result = run_pipeline(_input(), events.append, cancel_event=cancel_event)
    assert result.case_id == "case_test"
    # Every stage emitted a "running" event
    running_stages = [e["stage"] for e in events if e.get("status") == "running"]
    assert running_stages == [
        "denial_analyzer",
        "policy_reader",
        "chart_miner",
        "guideline_citer",
        "letter_writer",
        "verifier",
    ]


def test_run_pipeline_cancelled_before_first_agent_does_no_work(stub_pipeline):
    """Cancel set before run_pipeline is even called — no agents run.

    Real-world: client disconnected during the initial handshake, before
    DenialAnalyzer's first call. We must not even start denial_analyzer.
    """
    cancel_event = threading.Event()
    cancel_event.set()
    events: list[dict] = []
    with pytest.raises(PipelineCancelled):
        run_pipeline(_input(), events.append, cancel_event=cancel_event)
    # NOT EVEN denial_analyzer should have emitted "running"
    assert events == []


def test_run_pipeline_cancelled_after_denial_analyzer_skips_remaining(stub_pipeline):
    """Real-world: client disconnects right after seeing the first
    'denial_analyzer done' event. The pipeline must stop before
    PolicyReader's Claude call — which would have cost ~$0.10.
    """
    cancel_event = threading.Event()
    events: list[dict] = []

    def cb(event: dict) -> None:
        events.append(event)
        if event.get("stage") == "denial_analyzer" and event.get("status") == "done":
            cancel_event.set()

    with pytest.raises(PipelineCancelled):
        run_pipeline(_input(), cb, cancel_event=cancel_event)
    running_stages = [e["stage"] for e in events if e.get("status") == "running"]
    # denial_analyzer ran but policy_reader DID NOT — proves we cancelled
    # at the agent boundary, not after starting the next agent.
    assert running_stages == ["denial_analyzer"]


def test_run_pipeline_cancelled_mid_pipeline_skips_remaining(stub_pipeline):
    """Real-world: ChartMiner just finished. Cancel kicks in.
    GuidelineCiter and LetterWriter must NOT run.
    """
    cancel_event = threading.Event()
    events: list[dict] = []

    def cb(event: dict) -> None:
        events.append(event)
        if event.get("stage") == "chart_miner" and event.get("status") == "done":
            cancel_event.set()

    with pytest.raises(PipelineCancelled):
        run_pipeline(_input(), cb, cancel_event=cancel_event)
    running_stages = [e["stage"] for e in events if e.get("status") == "running"]
    assert running_stages == ["denial_analyzer", "policy_reader", "chart_miner"]
    # GuidelineCiter and LetterWriter and Verifier never started
    assert "guideline_citer" not in running_stages
    assert "letter_writer" not in running_stages
    assert "verifier" not in running_stages


def test_run_pipeline_cancelled_just_before_verifier_skips_verifier(stub_pipeline):
    """Edge case: cancel right after letter_writer 'done'. Verifier
    is local-only (no Claude call) but we still respect cancel —
    consistency matters more than the trivial saving here.
    """
    cancel_event = threading.Event()
    events: list[dict] = []

    def cb(event: dict) -> None:
        events.append(event)
        if event.get("stage") == "letter_writer" and event.get("status") == "done":
            cancel_event.set()

    with pytest.raises(PipelineCancelled):
        run_pipeline(_input(), cb, cancel_event=cancel_event)
    running_stages = [e["stage"] for e in events if e.get("status") == "running"]
    assert running_stages[-1] == "letter_writer"
    assert "verifier" not in running_stages


def test_run_pipeline_default_cancel_event_is_none(stub_pipeline):
    """Backward-compat: callers (existing tests, scripts) that don't
    pass cancel_event must keep working unchanged."""
    events: list[dict] = []
    result = run_pipeline(_input(), events.append)
    assert result.case_id == "case_test"
    assert any(e.get("stage") == "verifier" and e.get("status") == "done" for e in events)
