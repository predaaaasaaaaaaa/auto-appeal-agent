"""
pdf_export.py — render an AppealDraft as a printable PDF.

The output has two sections:

  1. The appeal letter itself: clean prose, no inline citation markers,
     formatted to look like a document a physician could sign.

  2. A "Citations audit" appendix: for each paragraph that contains
     citations, lists every CitationMarker — its source type, source_id,
     and the verbatim quote that supports the claim. This is what
     distinguishes a generated letter from any other LLM output: the
     receipts are part of the document.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fpdf import FPDF

from auto_appeal_agent.schemas import AppealDraft

# Default fpdf2 fonts (Helvetica) only cover Latin-1. Replace common
# Unicode punctuation with ASCII equivalents so we don't crash on smart
# quotes, em-dashes, etc. that the LetterWriter often produces.
_UNICODE_REPLACEMENTS = {
    "—": "--",
    "–": "-",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "…": "...",
    " ": " ",
    "•": "*",
    "·": "*",
    "≥": ">=",
    "≤": "<=",
}


def _sanitize(text: str) -> str:
    for u, a in _UNICODE_REPLACEMENTS.items():
        text = text.replace(u, a)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _line(pdf: FPDF, text: str, h: float = 6) -> None:
    """Write one line and move cursor to the next row at the left margin."""
    pdf.cell(0, h, _sanitize(text), new_x="LMARGIN", new_y="NEXT")


def _para(pdf: FPDF, text: str, h: float = 6) -> None:
    """Write a paragraph (multi-line) and reset cursor to the left margin."""
    pdf.multi_cell(0, h, _sanitize(text), new_x="LMARGIN", new_y="NEXT")


def render_appeal_pdf(
    draft: AppealDraft,
    *,
    physician_name: str = "[Physician Name]",
    physician_credentials: str = "MD",
    today: Optional[str] = None,
) -> bytes:
    """Render the AppealDraft to PDF bytes."""
    pdf = FPDF(format="Letter", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(left=22, right=22, top=22)
    pdf.add_page()

    today_str = today or date.today().isoformat()

    pdf.set_font("Helvetica", "", 11)
    _line(pdf, today_str)
    pdf.ln(8)

    # Recipient block
    _line(pdf, "To:")
    _line(pdf, draft.recipient_plan)
    _line(pdf, "Medical Review Department")
    pdf.ln(8)

    # Subject line
    pdf.set_font("Helvetica", "B", 11)
    _para(pdf, f"RE: {draft.subject_line}")
    pdf.set_font("Helvetica", "", 11)
    pdf.ln(4)

    _line(pdf, "To Whom It May Concern,")
    pdf.ln(4)

    # Body
    for p in draft.paragraphs:
        if p.heading:
            pdf.set_font("Helvetica", "B", 11)
            _para(pdf, p.heading)
            pdf.set_font("Helvetica", "", 11)
            pdf.ln(1)
        _para(pdf, p.text)
        pdf.ln(4)

    # Closing
    pdf.ln(6)
    _line(pdf, "Respectfully,")
    pdf.ln(14)
    _line(pdf, f"{physician_name}, {physician_credentials}")

    # Citations audit appendix
    has_citations = any(p.citations for p in draft.paragraphs)
    if has_citations:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 12)
        _line(pdf, "Citations audit")
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 9)
        _para(
            pdf,
            "Every factual claim in the appeal above was extracted by an AI "
            "agent and independently re-verified against the source documents "
            "listed below. Each citation shows the source it points to and "
            "the verbatim quote that supports the claim.",
            h=4,
        )
        pdf.ln(4)

        for i, p in enumerate(draft.paragraphs):
            if not p.citations:
                continue
            pdf.set_font("Helvetica", "B", 10)
            heading = p.heading or f"Paragraph {i + 1}"
            _para(pdf, heading, h=5)
            pdf.set_font("Helvetica", "", 9)
            for c in p.citations:
                _para(
                    pdf,
                    f"  * [{c.source_type} :: {c.source_id}] "
                    f"\"{c.verbatim_quote}\"",
                    h=4,
                )
                pdf.ln(1)
            pdf.ln(2)

    return bytes(pdf.output())
