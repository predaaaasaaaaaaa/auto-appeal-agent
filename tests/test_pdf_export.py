"""
PDF export tests.

Pure unit tests — no API calls. Verify that:
  * a well-formed AppealDraft renders to a valid PDF (parses with PyMuPDF),
  * the rendered PDF text contains the subject, recipient, paragraph
    headings/body, and the citations audit appendix,
  * unicode characters that fpdf2 can't natively encode are sanitized
    rather than crashing the renderer.
"""
from __future__ import annotations

import io

import fitz  # PyMuPDF

from auto_appeal_agent.pdf_export import render_appeal_pdf
from auto_appeal_agent.schemas import (
    AppealDraft,
    AppealParagraph,
    CitationMarker,
)


def _sample_draft(text: str = "The patient meets every criterion.") -> AppealDraft:
    return AppealDraft(
        case_id="case_unit",
        recipient_plan="ACME Health Plus",
        subject_line="Appeal of prior authorization denial — Test",
        paragraphs=[
            AppealParagraph(
                heading="Medical necessity met: BMI threshold",
                text=text,
                citations=[
                    CitationMarker(
                        claim="The patient's BMI is 34.2",
                        source_type="patient_chart",
                        source_id="chart_q1",
                        verbatim_quote="BMI 34.2",
                    )
                ],
            )
        ],
    )


def _pdf_text(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf")
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


def test_render_returns_valid_pdf_bytes():
    pdf_bytes = render_appeal_pdf(_sample_draft())
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 1000


def test_rendered_pdf_contains_letter_content():
    draft = _sample_draft()
    text = _pdf_text(render_appeal_pdf(draft))

    assert "ACME Health Plus" in text
    assert "Appeal of prior authorization denial" in text
    assert "Medical necessity met: BMI threshold" in text
    assert "The patient meets every criterion." in text


def test_rendered_pdf_includes_citations_audit():
    text = _pdf_text(render_appeal_pdf(_sample_draft()))
    assert "Citations audit" in text
    assert "patient_chart" in text
    assert "chart_q1" in text
    assert "BMI 34.2" in text


def test_unicode_characters_are_sanitized():
    """Smart quotes, em-dashes, and non-Latin-1 chars must not crash fpdf2."""
    draft = _sample_draft(
        text=(
            "Patient’s BMI is “34.2” — well above the "
            "policy threshold of ≥ 30."
        )
    )
    pdf_bytes = render_appeal_pdf(draft)
    assert pdf_bytes.startswith(b"%PDF-")
    text = _pdf_text(pdf_bytes)
    assert "BMI" in text
    assert ">=" in text or ">" in text  # >= replacement


def test_renders_with_no_citations():
    """A draft with no citations should still render (no audit page)."""
    draft = AppealDraft(
        case_id="case_no_cites",
        recipient_plan="ACME",
        subject_line="No citations",
        paragraphs=[
            AppealParagraph(
                heading="Plain paragraph",
                text="No citations here.",
                citations=[],
            )
        ],
    )
    pdf_bytes = render_appeal_pdf(draft)
    text = _pdf_text(pdf_bytes)
    assert "No citations here." in text
    # Audit appendix should NOT appear when no citations exist.
    assert "Citations audit" not in text
