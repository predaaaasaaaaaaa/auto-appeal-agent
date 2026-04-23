"""
Run the full pipeline on one fixture case and write the results to disk.

Usage:
    .venv/bin/python -m auto_appeal_agent.scripts.run_case case_01_ozempic_bmi34

Outputs (written to `output/<case_id>/`):
    appeal_letter.md         — the appeal letter, as it would be sent.
    verification_report.md   — citation-by-citation audit.
    pipeline.json            — full structured VerifiedAppeal for inspection.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from auto_appeal_agent.formatter import (
    render_appeal_letter,
    render_verification_report,
)
from auto_appeal_agent.orchestrator import run_pipeline
from auto_appeal_agent.schemas import PipelineInput

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_ROOT = REPO_ROOT / "fixtures"
OUTPUT_ROOT = REPO_ROOT / "output"


def run_case(case_id: str) -> Path:
    case_dir = FIXTURES_ROOT / case_id
    if not case_dir.is_dir():
        raise SystemExit(f"fixture not found: {case_dir}")

    pipeline_input = PipelineInput(
        case_id=case_id,
        denial_letter_path=str(case_dir / "denial_letter.pdf"),
        patient_chart_path=str(case_dir / "patient_chart.txt"),
        payer_policy_path=str(case_dir / "payer_policy.pdf"),
    )

    print(f"Running pipeline on {case_id}...")
    verified = run_pipeline(pipeline_input)

    out_dir = OUTPUT_ROOT / case_id
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "appeal_letter.md").write_text(
        render_appeal_letter(verified) + "\n", encoding="utf-8"
    )
    (out_dir / "verification_report.md").write_text(
        render_verification_report(verified) + "\n", encoding="utf-8"
    )
    (out_dir / "pipeline.json").write_text(
        verified.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )

    print(f"  pass_rate={verified.verification_pass_rate:.1%}")
    print(f"  ready_to_send={verified.ready_to_send}")
    print(f"  verified={len(verified.verified_citations)} "
          f"rejected={len(verified.rejected_citations)}")
    print(f"  wrote: {out_dir}")
    return out_dir


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python -m auto_appeal_agent.scripts.run_case <case_id>")
    run_case(sys.argv[1])


if __name__ == "__main__":
    main()
