"""
Unit tests for pdf_utils helpers. No API calls.
"""
from __future__ import annotations

import base64
from pathlib import Path

from auto_appeal_agent.pdf_utils import extract_text, render_pdf_to_image_blocks


def test_extract_text_on_case_01(fixtures_dir: Path):
    text = extract_text(fixtures_dir / "case_01_ozempic_bmi34" / "denial_letter.pdf")
    assert "[Page 1]" in text
    assert "semaglutide" in text.lower() or "ozempic" in text.lower()
    assert "bluesun" in text.lower()


def test_render_pdf_to_image_blocks_structure(fixtures_dir: Path):
    blocks = render_pdf_to_image_blocks(
        fixtures_dir / "case_01_ozempic_bmi34" / "denial_letter.pdf"
    )
    assert len(blocks) >= 1, "expected at least one page"
    b = blocks[0]
    assert b["type"] == "image"
    assert b["source"]["type"] == "base64"
    assert b["source"]["media_type"] == "image/png"
    # base64 payload must decode cleanly to a PNG
    raw = base64.b64decode(b["source"]["data"])
    assert raw.startswith(b"\x89PNG\r\n\x1a\n"), "payload is not a PNG"
