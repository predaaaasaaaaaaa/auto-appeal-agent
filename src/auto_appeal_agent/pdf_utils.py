"""
pdf_utils.py — shared PDF helpers.

Two helpers used across agents:

  * `render_pdf_to_image_blocks(path)` — renders every page to a PNG and
    returns a list of Anthropic image content blocks. Used when the
    agent needs Claude's vision (e.g. DenialAnalyzer — scanned letters
    may have handwritten annotations or fax-transmission artifacts).

  * `extract_text(path)` — extracts the machine-readable text layer of
    the PDF. Used when verbatim fidelity matters more than layout (e.g.
    PolicyReader — policy documents are digital and a copy-paste from
    the text layer is exact, which is important because the Verifier
    matches source quotes character-for-character).

Consumers are free to use both on the same document and pass both the
text and the images to Claude.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

# A US-Letter page at 150 DPI is ~1275x1650 pixels, well under Claude
# 4.7's 2576-pixel / 3.75-megapixel limits and plenty of resolution to
# read body text and footnotes.
DEFAULT_DPI = 150


def extract_text(pdf_path) -> str:
    """Return the PDF's full text with page markers.

    Page markers (`[Page N]`) help Claude report human-readable
    `quote_location` values like 'page 1, paragraph 2'.
    """
    doc = fitz.open(Path(pdf_path))
    try:
        return "\n\n".join(
            f"[Page {i + 1}]\n{page.get_text()}" for i, page in enumerate(doc)
        )
    finally:
        doc.close()


def render_pdf_to_image_blocks(
    pdf_path,
    dpi: int = DEFAULT_DPI,
) -> list[dict[str, Any]]:
    """Render a PDF's pages as Anthropic image content blocks."""
    doc = fitz.open(Path(pdf_path))
    blocks: list[dict[str, Any]] = []
    try:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            png_bytes = pix.tobytes("png")
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(png_bytes).decode("ascii"),
                    },
                }
            )
    finally:
        doc.close()
    return blocks
