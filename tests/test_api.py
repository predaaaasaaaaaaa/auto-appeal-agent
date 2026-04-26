"""
FastAPI endpoint tests.

Covers:
  - Non-LLM endpoints (/health, /cases, /source, /export_pdf).
  - The /run SSE failure path — we inject a raising agent and confirm
    an `{"stage":"error"}` event actually reaches the client. The
    happy-path SSE stream is exercised in tests/test_fixtures.py
    (cassette-backed) and in manual end-to-end runs.
"""
from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from auto_appeal_agent.api import main as api_main
from auto_appeal_agent.api.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_list_cases_returns_five():
    r = client.get("/api/cases")
    assert r.status_code == 200
    data = r.json()
    assert "cases" in data
    assert len(data["cases"]) == 5
    ids = [c["case_id"] for c in data["cases"]]
    assert "case_01_ozempic_bmi34" in ids
    assert "case_05_adalimumab_ra" in ids


def test_get_source_text_chart():
    r = client.get("/api/case/case_01_ozempic_bmi34/source/patient_chart")
    assert r.status_code == 200
    assert "BMI" in r.json()["text"]


def test_get_source_text_denial_pdf():
    r = client.get("/api/case/case_01_ozempic_bmi34/source/denial_letter")
    assert r.status_code == 200
    assert "BlueSun" in r.json()["text"] or "bluesun" in r.json()["text"].lower()


def test_unknown_source_kind_returns_400():
    r = client.get("/api/case/case_01_ozempic_bmi34/source/unknown")
    assert r.status_code == 400


def test_unknown_case_returns_404():
    r = client.get("/api/case/does_not_exist/source/patient_chart")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Path-traversal hardening — simulate every realistic attack shape.
# ---------------------------------------------------------------------------


def test_case_source_rejects_dot_dot_traversal():
    """Classic `..` traversal: try to read /etc/passwd via case_id.
    Must NOT escape FIXTURES_ROOT — must return 404 (with no detail
    leaking the attempted path)."""
    r = client.get("/api/case/..%2F..%2Fetc%2Fpasswd/source/patient_chart")
    # FastAPI may normalize this to either 404 or 400 depending on
    # routing; either way it must NOT 200.
    assert r.status_code in (400, 404)


def test_case_source_rejects_absolute_path():
    """An absolute case_id must not bypass the fixtures root."""
    r = client.get("/api/case/%2Fetc%2Fpasswd/source/patient_chart")
    assert r.status_code in (400, 404)


def test_run_rejects_dot_dot_traversal():
    """Same protection on the expensive endpoint — never spawn a
    pipeline against a path outside fixtures."""
    r = client.get("/api/run/..%2F..%2Fetc%2Fpasswd")
    assert r.status_code in (400, 404)


def test_resolve_case_dir_helper_rejects_outside_fixtures():
    """Direct unit-test of the helper. case_id values that resolve
    outside FIXTURES_ROOT must raise HTTPException(404)."""
    from fastapi import HTTPException

    from auto_appeal_agent.api.main import _resolve_case_dir

    for evil_id in (
        "../etc",
        "../../etc",
        "../../../etc/passwd",
        "case_01_ozempic_bmi34/../../../etc",
    ):
        with pytest.raises(HTTPException) as exc:
            _resolve_case_dir(evil_id)
        assert exc.value.status_code == 404


def test_resolve_case_dir_helper_accepts_real_case():
    """Sanity: a real case id resolves inside FIXTURES_ROOT and is
    returned as a Path the caller can then `.is_dir()`-check."""
    from auto_appeal_agent.api.main import (
        _FIXTURES_ROOT_RESOLVED,
        _resolve_case_dir,
    )

    p = _resolve_case_dir("case_01_ozempic_bmi34")
    assert p.is_relative_to(_FIXTURES_ROOT_RESOLVED)
    assert p.is_dir()


# ---------------------------------------------------------------------------
# Content-Disposition header injection — attacker-controlled case_id
# must NOT reach the response header raw.
# ---------------------------------------------------------------------------


def test_safe_filename_strips_crlf():
    """CRLF in case_id would let an attacker inject HTTP headers via
    Content-Disposition. The sanitizer must drop them."""
    from auto_appeal_agent.api.main import _safe_filename

    out = _safe_filename("test\r\nContent-Type: text/html")
    assert "\r" not in out
    assert "\n" not in out
    assert ":" not in out


def test_safe_filename_strips_quotes():
    """Double quotes break the filename="..." syntax and let an
    attacker append additional disposition params."""
    from auto_appeal_agent.api.main import _safe_filename

    out = _safe_filename('x"; filename="evil')
    assert '"' not in out
    assert ";" not in out


def test_safe_filename_preserves_valid_case_id():
    """Sanity: real case_id values pass through unchanged."""
    from auto_appeal_agent.api.main import _safe_filename

    assert _safe_filename("case_01_ozempic_bmi34") == "case_01_ozempic_bmi34_appeal.pdf"


def test_safe_filename_truncates_long_input():
    """A 100kB case_id shouldn't produce a 100kB header value."""
    from auto_appeal_agent.api.main import _safe_filename

    out = _safe_filename("a" * 10000)
    # Sanitized portion <= 64 chars + "_appeal.pdf" suffix
    assert len(out) <= 64 + len("_appeal.pdf")


def test_safe_filename_handles_empty_input():
    """Edge case — empty case_id must produce a non-empty filename."""
    from auto_appeal_agent.api.main import _safe_filename

    assert _safe_filename("") == "appeal_appeal.pdf"


def test_export_pdf_endpoint_strips_header_injection_attempt():
    """End-to-end: posting a malicious case_id must produce a
    Content-Disposition header with no CRLF / no extra header
    after the filename."""
    draft = {
        "case_id": "evil\r\nX-Injected: yes",
        "recipient_plan": "ACME",
        "subject_line": "T",
        "paragraphs": [{"heading": None, "text": "x", "citations": []}],
    }
    r = client.post("/api/export_pdf", json=draft)
    assert r.status_code == 200
    cd = r.headers.get("content-disposition", "")
    # Critical: no CRLF in the header value — that's what would
    # inject a separate header line.
    assert "\r" not in cd
    assert "\n" not in cd
    # The injected response header must NOT be present as its own header.
    # (Substring "x-injected" can legally appear inside the filename
    # because hyphens are an allowed filename character — that's just
    # text, not a real header line.)
    assert "x-injected" not in {k.lower() for k in r.headers.keys()}


def test_export_pdf_returns_application_pdf():
    draft = {
        "case_id": "case_test",
        "recipient_plan": "ACME",
        "subject_line": "Test",
        "paragraphs": [
            {
                "heading": "h",
                "text": "body",
                "citations": [],
            }
        ],
    }
    r = client.post("/api/export_pdf", json=draft)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert "case_test_appeal.pdf" in r.headers.get("content-disposition", "")
    assert r.content.startswith(b"%PDF-")


def test_export_pdf_rejects_malformed_draft():
    r = client.post("/api/export_pdf", json={"case_id": "bad"})
    assert r.status_code == 422  # Pydantic validation error from FastAPI


def test_run_emits_sse_error_when_pipeline_raises(monkeypatch):
    """Reliability: a hung or failing agent must surface an SSE error
    event, not hang the UI forever.

    We monkey-patch run_pipeline to raise after emitting one "running"
    progress event (simulating an agent that dies mid-call, which is
    what happens when Claude times out or the tool call fails). The
    stream must deliver the running event AND then a well-formed
    `{"stage":"error"}` event before closing.
    """
    def fake_pipeline(
        pipeline_input,
        progress_callback=None,
        second_pass=False,
        cancel_event=None,
    ):
        if progress_callback is not None:
            progress_callback({"stage": "denial_analyzer", "status": "running"})
        raise RuntimeError(
            "simulated hang: Claude returned no tool_use block"
        )

    monkeypatch.setattr(api_main, "run_pipeline", fake_pipeline)

    events = []
    with client.stream("GET", "/api/run/case_01_ozempic_bmi34") as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
            if events and events[-1].get("stage") == "error":
                break

    stages = [e.get("stage") for e in events]
    assert "denial_analyzer" in stages, (
        f"expected progress event before failure, got {events}"
    )
    error_events = [e for e in events if e.get("stage") == "error"]
    assert len(error_events) == 1, f"expected exactly one error, got {events}"
    err = error_events[0]
    assert err["error_type"] == "RuntimeError"
    assert "no tool_use block" in err["message"]


def test_module_has_logger_defined():
    """Regression for 2026-04-26 security audit: the SSE handler's
    PipelineCancelled catch logs via `logger.info`. If `logger` is
    undefined at module scope, the cancel path crashes silently
    inside an already-closing response. This test pins that
    `logger` exists and is a real Logger instance."""
    import logging as _logging

    assert hasattr(api_main, "logger"), (
        "api/main.py must define a module-level `logger` — without it "
        "the cancel-on-disconnect path raises NameError"
    )
    assert isinstance(api_main.logger, _logging.Logger)


def test_run_passes_cancel_event_to_pipeline(monkeypatch):
    """Wiring check: every call to /api/run/{case_id} must pass a
    threading.Event as `cancel_event` to run_pipeline. Without it,
    the orchestrator's cooperative cancellation has nothing to
    check — and a client disconnect would leave the pipeline
    burning Claude calls until natural completion.

    The end-to-end disconnect-propagation behavior is hard to test
    via fastapi.testclient.TestClient (which doesn't faithfully
    emulate ASGI disconnect signals on stream exit). The
    orchestrator-level cancellation primitive is fully covered in
    tests/test_pipeline_cancellation.py — 9 tests prove
    `cancel_event.set()` aborts the pipeline at the next agent
    boundary. This test pins the remaining contract: the API
    actually constructs and passes one.
    """
    captured: dict = {}

    def fake_pipeline(
        pipeline_input,
        progress_callback=None,
        second_pass=False,
        cancel_event=None,
    ):
        captured["cancel_event"] = cancel_event
        captured["second_pass"] = second_pass
        if progress_callback is not None:
            progress_callback({"stage": "denial_analyzer", "status": "running"})
        # Return a minimal valid VerifiedAppeal so the response
        # completes cleanly and we can inspect captured state.
        from auto_appeal_agent.schemas import (
            AppealDraft,
            AppealParagraph,
            VerifiedAppeal,
        )

        return VerifiedAppeal(
            case_id="case_01_ozempic_bmi34",
            draft=AppealDraft(
                case_id="case_01_ozempic_bmi34",
                recipient_plan="x",
                subject_line="x",
                paragraphs=[AppealParagraph(text="x", citations=[])],
            ),
            verified_citations=[],
            rejected_citations=[],
            verification_pass_rate=1.0,
            ready_to_send=True,
        )

    monkeypatch.setattr(api_main, "run_pipeline", fake_pipeline)

    with client.stream("GET", "/api/run/case_01_ozempic_bmi34") as r:
        assert r.status_code == 200
        # Drain the stream so the runner task completes.
        for _ in r.iter_lines():
            pass

    assert isinstance(captured.get("cancel_event"), threading.Event), (
        f"API must pass a threading.Event as cancel_event; "
        f"got {type(captured.get('cancel_event'))!r}"
    )
    # Sanity: second_pass is False by default; the API doesn't (yet)
    # surface a query param to flip it on. If that ever changes,
    # this assertion catches an accidental flip.
    assert captured.get("second_pass") is False
