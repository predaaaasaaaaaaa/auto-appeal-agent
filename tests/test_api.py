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
    def fake_pipeline(pipeline_input, progress_callback=None, second_pass=False):
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
