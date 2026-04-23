"""
FastAPI endpoint tests.

Only covers non-LLM endpoints (/health, /cases, /source). The /run
endpoint is exercised manually / by the end-to-end UI tests since it
calls real Claude.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

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
