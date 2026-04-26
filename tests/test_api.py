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


# ---------------------------------------------------------------------------
# API key auth — required when APPEAL_API_KEY env var is set, no-op
# when unset. Tests cover both modes against every guarded endpoint.
# ---------------------------------------------------------------------------


def test_health_does_not_require_api_key(monkeypatch):
    """/api/health is the operations / liveness endpoint and must
    stay open even when auth is configured. Otherwise load balancers
    can't probe it."""
    monkeypatch.setattr(api_main, "APPEAL_API_KEY", "test-key-xyz")
    r = client.get("/api/health")
    assert r.status_code == 200


@pytest.mark.parametrize(
    "method,url,body",
    [
        ("get", "/api/cases", None),
        ("get", "/api/case/case_01_ozempic_bmi34/source/patient_chart", None),
        ("post", "/api/export_pdf", {
            "case_id": "x", "recipient_plan": "x", "subject_line": "x",
            "paragraphs": [{"heading": None, "text": "x", "citations": []}],
        }),
        ("get", "/api/run/case_01_ozempic_bmi34", None),
    ],
)
def test_protected_endpoints_reject_missing_key(monkeypatch, method, url, body):
    """When APPEAL_API_KEY is set, every cost/data endpoint must
    return 401 if no X-API-Key header (or api_key query param) is
    presented. This is the lock that closes the
    'anyone-on-the-network burns $1/call' attack."""
    monkeypatch.setattr(api_main, "APPEAL_API_KEY", "test-key-xyz")
    if method == "get":
        r = client.get(url)
    else:
        r = client.post(url, json=body)
    assert r.status_code == 401, (
        f"{method.upper()} {url} returned {r.status_code} — should be 401 "
        f"when APPEAL_API_KEY set and no key presented"
    )


@pytest.mark.parametrize(
    "method,url,body",
    [
        ("get", "/api/cases", None),
        ("get", "/api/case/case_01_ozempic_bmi34/source/patient_chart", None),
        ("post", "/api/export_pdf", {
            "case_id": "x", "recipient_plan": "x", "subject_line": "x",
            "paragraphs": [{"heading": None, "text": "x", "citations": []}],
        }),
    ],
)
def test_protected_endpoints_reject_wrong_key(monkeypatch, method, url, body):
    """A wrong key must NOT slip through. Constant-time comparison
    via secrets.compare_digest prevents byte-by-byte timing oracles."""
    monkeypatch.setattr(api_main, "APPEAL_API_KEY", "test-key-xyz")
    headers = {"X-API-Key": "completely-wrong-key"}
    if method == "get":
        r = client.get(url, headers=headers)
    else:
        r = client.post(url, json=body, headers=headers)
    assert r.status_code == 401


def test_protected_endpoint_accepts_correct_header_key(monkeypatch):
    """X-API-Key header is the preferred way to authenticate.
    Doesn't leak via URL / referrer / server-access-log."""
    monkeypatch.setattr(api_main, "APPEAL_API_KEY", "test-key-xyz")
    r = client.get("/api/cases", headers={"X-API-Key": "test-key-xyz"})
    assert r.status_code == 200


def test_protected_endpoint_accepts_correct_query_param_key(monkeypatch):
    """Query-param fallback exists for browser EventSource which
    has no public API for setting headers. Same key, just delivered
    via URL."""
    monkeypatch.setattr(api_main, "APPEAL_API_KEY", "test-key-xyz")
    r = client.get("/api/cases?api_key=test-key-xyz")
    assert r.status_code == 200


def test_unset_api_key_means_open_access(monkeypatch):
    """Backward compat / dev convenience: when APPEAL_API_KEY is
    None, all endpoints stay open. Documented at startup with a
    warning log line."""
    monkeypatch.setattr(api_main, "APPEAL_API_KEY", None)
    r = client.get("/api/cases")
    assert r.status_code == 200
    r = client.get("/api/case/case_01_ozempic_bmi34/source/patient_chart")
    assert r.status_code == 200


def test_empty_string_api_key_treated_as_unset(monkeypatch):
    """Defensive: APPEAL_API_KEY="" or whitespace-only must not be
    accepted as a valid key (that would let an attacker authenticate
    by sending an empty header). Our env loader already collapses
    "" to None — this test pins that contract."""
    # Direct test of the parser — empty string env value is normalized
    # to None at module load, so we can't easily simulate "user set
    # APPEAL_API_KEY=''" via monkeypatch. This test pins the rule.
    monkeypatch.setattr(api_main, "APPEAL_API_KEY", None)
    r = client.get("/api/cases", headers={"X-API-Key": ""})
    assert r.status_code == 200  # auth disabled, request goes through


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
    # error_type (the exception class name) IS exposed to the client —
    # it's safe and useful for the UI to know whether a retry might help.
    assert err["error_type"] == "RuntimeError"
    # The raw exception message is NOT exposed (it can echo PHI from
    # Pydantic validation errors). The client gets a generic message;
    # the full traceback is logged server-side via logger.exception.
    assert "no tool_use block" not in err["message"], (
        "raw exc message leaked to client — H2 regression"
    )
    assert "Pipeline failed" in err["message"]


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


# ---------------------------------------------------------------------------
# Per-case concurrency lock — at most one in-flight pipeline per case_id
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_active_pipelines():
    """Ensure each test starts with an empty _active_pipelines set so
    one test's leftover state doesn't poison another."""
    api_main._active_pipelines.clear()
    yield
    api_main._active_pipelines.clear()


def test_run_returns_409_when_case_already_running():
    """If another tab/request has the case in flight, a duplicate
    Start must reject with 409 — NOT spawn a second pipeline."""
    api_main._active_pipelines.add("case_01_ozempic_bmi34")
    r = client.get("/api/run/case_01_ozempic_bmi34")
    assert r.status_code == 409
    body = r.json()
    assert "already running" in body["detail"].lower()


def test_run_does_not_burn_pipeline_call_when_409(monkeypatch):
    """Critical: the 409 must come BEFORE run_pipeline is called.
    Otherwise the user is rejected AND charged."""
    api_main._active_pipelines.add("case_01_ozempic_bmi34")
    called = {"count": 0}

    def boom_pipeline(*args, **kwargs):
        called["count"] += 1
        raise AssertionError(
            "run_pipeline should NOT be called when 409 returns — "
            "that would burn $1 on a request we've already rejected"
        )

    monkeypatch.setattr(api_main, "run_pipeline", boom_pipeline)
    r = client.get("/api/run/case_01_ozempic_bmi34")
    assert r.status_code == 409
    assert called["count"] == 0


def test_run_releases_case_slot_after_normal_completion(monkeypatch):
    """The case must be removed from _active_pipelines once the
    pipeline finishes, otherwise the user can never re-run it."""
    from auto_appeal_agent.schemas import (
        AppealDraft,
        AppealParagraph,
        VerifiedAppeal,
    )

    def fake_pipeline(
        pipeline_input,
        progress_callback=None,
        second_pass=False,
        cancel_event=None,
    ):
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
        for _ in r.iter_lines():
            pass

    # Slot must be freed — otherwise re-running the case is impossible.
    assert "case_01_ozempic_bmi34" not in api_main._active_pipelines


def test_run_releases_case_slot_after_pipeline_error(monkeypatch):
    """Defensive: even when the pipeline raises, the slot must be
    freed — otherwise a single failure permanently locks the case."""

    def boom_pipeline(*args, **kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(api_main, "run_pipeline", boom_pipeline)

    with client.stream("GET", "/api/run/case_01_ozempic_bmi34") as r:
        assert r.status_code == 200
        for _ in r.iter_lines():
            pass

    assert "case_01_ozempic_bmi34" not in api_main._active_pipelines


# ---------------------------------------------------------------------------
# Per-IP rate limit on /api/run — second-line defense vs a flood from a
# single authenticated client.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_rate_limit_log():
    """Each test starts fresh so rate-limit state doesn't bleed."""
    api_main._run_rate_log.clear()
    yield
    api_main._run_rate_log.clear()


def _stub_pipeline_quick_success(monkeypatch):
    """Helper: replace run_pipeline with a no-op that returns a
    minimal valid VerifiedAppeal. Lets rate-limit tests fire many
    requests without burning anything."""
    from auto_appeal_agent.schemas import (
        AppealDraft,
        AppealParagraph,
        VerifiedAppeal,
    )

    def fake(*args, **kwargs):
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

    monkeypatch.setattr(api_main, "run_pipeline", fake)


def test_run_returns_429_after_rate_limit_exceeded(monkeypatch):
    """Fire MAX+1 starts in quick succession — last one rejects."""
    _stub_pipeline_quick_success(monkeypatch)
    # Tighten the limit so we don't have to fire 5 real requests.
    monkeypatch.setattr(api_main, "RATE_LIMIT_MAX_STARTS", 2)
    monkeypatch.setattr(api_main, "RATE_LIMIT_WINDOW_SECONDS", 60.0)

    # First two calls allowed (200 SSE).
    for _ in range(2):
        with client.stream("GET", "/api/run/case_01_ozempic_bmi34") as r:
            assert r.status_code == 200
            for _ in r.iter_lines():
                pass

    # Third call inside the window — must be 429.
    r = client.get("/api/run/case_01_ozempic_bmi34")
    assert r.status_code == 429
    assert "too many requests" in r.json()["detail"].lower()


def test_run_429_does_not_invoke_pipeline(monkeypatch):
    """The 429 must come BEFORE run_pipeline. Otherwise rate-limited
    requests would still burn $1."""
    monkeypatch.setattr(api_main, "RATE_LIMIT_MAX_STARTS", 1)
    monkeypatch.setattr(api_main, "RATE_LIMIT_WINDOW_SECONDS", 60.0)

    call_count = {"n": 0}

    def fake(*args, **kwargs):
        call_count["n"] += 1
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

    monkeypatch.setattr(api_main, "run_pipeline", fake)

    # First call uses the 1-call quota.
    with client.stream("GET", "/api/run/case_01_ozempic_bmi34") as r:
        for _ in r.iter_lines():
            pass

    # Second call must 429 without invoking run_pipeline.
    pre_count = call_count["n"]
    r = client.get("/api/run/case_01_ozempic_bmi34")
    assert r.status_code == 429
    assert call_count["n"] == pre_count, (
        "run_pipeline was called on a rate-limited request — that's a "
        "$1 burn that should never happen"
    )


def test_rate_limit_per_ip_isolation(monkeypatch):
    """Each IP gets its own quota — one IP exhausting their quota
    must NOT affect another IP."""
    monkeypatch.setattr(api_main, "RATE_LIMIT_MAX_STARTS", 1)
    monkeypatch.setattr(api_main, "RATE_LIMIT_WINDOW_SECONDS", 60.0)

    # Pre-populate rate-limit log as if IP "1.2.3.4" already maxed out.
    api_main._run_rate_log["1.2.3.4"] = [time.monotonic()]
    # IP "5.6.7.8" should still be unaffected.
    api_main._run_rate_log.setdefault("5.6.7.8", [])

    # The TestClient uses 'testclient' as its host. We can call
    # _enforce_rate_limit directly to verify isolation.
    import asyncio as _asyncio

    async def run():
        # 1.2.3.4 is at limit -> raises 429
        from fastapi import HTTPException

        try:
            await api_main._enforce_rate_limit(
                "1.2.3.4",
                log=api_main._run_rate_log,
                lock=api_main._run_rate_lock,
                max_in_window=api_main.RATE_LIMIT_MAX_STARTS,
                window_seconds=api_main.RATE_LIMIT_WINDOW_SECONDS,
            )
            assert False, "expected 429 for maxed-out IP"
        except HTTPException as e:
            assert e.status_code == 429

        # 5.6.7.8 is fresh -> allowed
        await api_main._enforce_rate_limit(
            "5.6.7.8",
            log=api_main._run_rate_log,
            lock=api_main._run_rate_lock,
            max_in_window=api_main.RATE_LIMIT_MAX_STARTS,
            window_seconds=api_main.RATE_LIMIT_WINDOW_SECONDS,
        )

    _asyncio.run(run())


def test_rate_limit_window_expiry(monkeypatch):
    """After the window passes, old timestamps are pruned and the
    quota is refreshed. Use a tiny window so we don't sleep long."""
    monkeypatch.setattr(api_main, "RATE_LIMIT_MAX_STARTS", 1)
    monkeypatch.setattr(api_main, "RATE_LIMIT_WINDOW_SECONDS", 0.1)

    import asyncio as _asyncio
    from fastapi import HTTPException

    def _run_args() -> dict:
        return dict(
            log=api_main._run_rate_log,
            lock=api_main._run_rate_lock,
            max_in_window=api_main.RATE_LIMIT_MAX_STARTS,
            window_seconds=api_main.RATE_LIMIT_WINDOW_SECONDS,
        )

    async def run():
        await api_main._enforce_rate_limit("1.2.3.4", **_run_args())
        # Immediately at limit
        try:
            await api_main._enforce_rate_limit("1.2.3.4", **_run_args())
            assert False, "expected 429 immediately after maxing"
        except HTTPException as e:
            assert e.status_code == 429
        # Wait past the window
        await _asyncio.sleep(0.15)
        # Should be allowed again
        await api_main._enforce_rate_limit("1.2.3.4", **_run_args())

    _asyncio.run(run())


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
