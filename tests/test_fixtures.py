"""
Fixture integrity + orchestrator-on-fixtures tests.

Plain-language summary: verifies the five synthetic cases on disk are
well-formed (all four files present, PDFs parse, chart text non-empty,
expected.json valid) and that the orchestrator can run through each
case end-to-end on stubs.

When Phase 1 un-stubs the agents, this file becomes the gate that says
"the whole pipeline still works on every case" after any change.
"""
from __future__ import annotations

import json
from pathlib import Path

import fitz  # PyMuPDF
import pytest

from auto_appeal_agent.orchestrator import run_pipeline
from auto_appeal_agent.schemas import PipelineInput

REQUIRED_FILES = ("denial_letter.pdf", "patient_chart.txt", "payer_policy.pdf", "expected.json")


def test_all_cases_present(all_case_dirs: list[Path]):
    """We expect exactly five synthetic cases."""
    assert len(all_case_dirs) == 5, (
        f"expected 5 cases, found {len(all_case_dirs)}: {[p.name for p in all_case_dirs]}"
    )


@pytest.mark.parametrize(
    "filename", REQUIRED_FILES, ids=lambda f: f
)
def test_every_case_has_required_file(all_case_dirs: list[Path], filename: str):
    missing = [d.name for d in all_case_dirs if not (d / filename).is_file()]
    assert not missing, f"cases missing {filename}: {missing}"


def test_denial_letter_pdfs_parse(all_case_dirs: list[Path]):
    for case_dir in all_case_dirs:
        pdf_path = case_dir / "denial_letter.pdf"
        doc = fitz.open(pdf_path)
        assert doc.page_count >= 1, f"{pdf_path} has no pages"
        text = doc[0].get_text()
        assert len(text.strip()) > 50, f"{pdf_path} page 1 text looks empty"
        doc.close()


def test_payer_policy_pdfs_parse(all_case_dirs: list[Path]):
    for case_dir in all_case_dirs:
        pdf_path = case_dir / "payer_policy.pdf"
        doc = fitz.open(pdf_path)
        assert doc.page_count >= 1
        assert len(doc[0].get_text().strip()) > 100
        doc.close()


def test_patient_charts_non_empty(all_case_dirs: list[Path]):
    for case_dir in all_case_dirs:
        chart = (case_dir / "patient_chart.txt").read_text()
        assert len(chart.strip()) > 200, f"{case_dir.name} chart looks too short"


def test_expected_json_parses(all_case_dirs: list[Path]):
    for case_dir in all_case_dirs:
        data = json.loads((case_dir / "expected.json").read_text())
        assert data["case_id"].startswith("case_")
        assert "expected_appeal" in data
        assert "key_claims" in data["expected_appeal"]


@pytest.mark.parametrize(
    "case_dir_name",
    [
        "case_01_ozempic_bmi34",
        "case_02_brain_mri_headache",
        "case_03_pt_extension",
        "case_04_cgm_t2dm_insulin",
        "case_05_adalimumab_ra",
    ],
)
def test_orchestrator_runs_on_each_case(cassette, fixtures_dir: Path, case_dir_name: str):  # noqa: ARG001
    """End-to-end: the pipeline produces a valid VerifiedAppeal for every case.

    As Phase 1 un-stubs each agent, this test starts hitting the real API.
    Marked @pytest.mark.integration so it runs only with `make test-integration`.
    """
    case_dir = fixtures_dir / case_dir_name
    pipeline_input = PipelineInput(
        case_id=case_dir_name,
        denial_letter_path=str(case_dir / "denial_letter.pdf"),
        patient_chart_path=str(case_dir / "patient_chart.txt"),
        payer_policy_path=str(case_dir / "payer_policy.pdf"),
    )
    result = run_pipeline(pipeline_input)
    assert result.case_id == case_dir_name
    # Phase 1 gate: 100% citation verification for every case.
    assert result.verification_pass_rate == 1.0
    assert result.ready_to_send is True
