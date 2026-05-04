"""PDF schedule extraction.

Uses pdfplumber for table-aware extraction. pdfplumber clusters absolutely-
positioned text fragments by y-coordinate to reconstruct rows, then infers
columns from x-positions — which loses much less information than naive
text scraping (the approach used by pdf.js in the browser for the FIRST
agenda parser).

Output shape: list of "table rows" where each row is a list of cell strings.
This is what we feed to the LLM — much closer to a real schedule table than
a flat text dump.
"""
from __future__ import annotations

import hashlib
import io
import logging
from typing import Any

import pdfplumber

log = logging.getLogger(__name__)

# Cap PDFs at a reasonable size. Beyond this is almost certainly a misuse
# (a 50-page document for a 92-match event would be ~5MB max). Stops
# memory exhaustion attacks via gigantic PDFs.
MAX_PDF_BYTES = 10 * 1024 * 1024   # 10 MB
# Cap pages because some PDFs have hundreds of decorative pages.
# A typical schedule PDF is 1-8 pages.
MAX_PAGES = 30


def hash_pdf(content: bytes) -> str:
    """Return SHA-256 hex digest of PDF bytes — used as cache key.

    Same bytes → same hash → same parsed result, regardless of filename.
    """
    return hashlib.sha256(content).hexdigest()


def extract_tables(content: bytes) -> dict[str, Any]:
    """Extract structured table data from a PDF.

    Returns:
        {
            "page_count":  int,
            "pages":       list of pages, each {
                "page_num":   1-based,
                "tables":     list of tables, each list of rows, each list of cells
                "text":       fallback text for pages with no detected tables
            },
            "metadata": {raw PDF metadata if useful},
            "byte_size": int,
        }

    Pages with no detected tables fall back to text extraction so we still
    have something to send the LLM. Some schedule PDFs use whitespace-aligned
    layouts that pdfplumber doesn't detect as tables; the LLM can still parse
    those from the text.
    """
    if len(content) > MAX_PDF_BYTES:
        raise ValueError(f"PDF too large: {len(content)} bytes (max {MAX_PDF_BYTES})")

    pages_out: list[dict[str, Any]] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        page_count = len(pdf.pages)
        if page_count > MAX_PAGES:
            raise ValueError(f"PDF too long: {page_count} pages (max {MAX_PAGES})")

        for i, page in enumerate(pdf.pages, start=1):
            # extract_tables returns list of tables, each is list of rows,
            # each row is list of cell strings (possibly None for empty cells).
            try:
                raw_tables = page.extract_tables() or []
            except Exception as e:
                log.warning("Table extraction failed on page %d: %s", i, e)
                raw_tables = []

            # Normalize: drop entirely-empty rows, replace None cells with "".
            tables_norm = []
            for tbl in raw_tables:
                rows = []
                for row in tbl:
                    cells = [c.strip() if c else "" for c in row]
                    if any(cells):  # skip rows that are entirely empty
                        rows.append(cells)
                if rows:
                    tables_norm.append(rows)

            # Always include text fallback. Some PDFs encode tables as
            # whitespace-aligned text without table borders, in which case
            # extract_tables() returns nothing but extract_text() still works.
            try:
                text = page.extract_text() or ""
            except Exception as e:
                log.warning("Text extraction failed on page %d: %s", i, e)
                text = ""

            pages_out.append({
                "page_num": i,
                "tables":   tables_norm,
                "text":     text,
            })

        meta = pdf.metadata or {}

    return {
        "page_count": page_count,
        "pages":      pages_out,
        "metadata": {
            "title":    meta.get("Title", ""),
            "author":   meta.get("Author", ""),
            "creator":  meta.get("Creator", ""),
            "subject":  meta.get("Subject", ""),
        },
        "byte_size": len(content),
    }


def estimate_token_budget(extracted: dict[str, Any]) -> int:
    """Rough token estimate for the LLM payload. Used to refuse PDFs that
    would exceed the context window. Roughly 4 chars per token for English.
    """
    total_chars = 0
    for page in extracted["pages"]:
        for tbl in page["tables"]:
            for row in tbl:
                total_chars += sum(len(c) for c in row) + len(row) * 2  # cell separators
        total_chars += len(page["text"])
    # Add ~2000 token overhead for the prompt itself
    return total_chars // 4 + 2000


def format_for_llm(extracted: dict[str, Any]) -> str:
    """Format the extracted tables/text for inclusion in an LLM prompt.

    Tables are rendered as pipe-delimited text rows (markdown-table style)
    because LLMs handle that format reliably. Text fallback is appended
    verbatim with a page marker.
    """
    parts: list[str] = []
    for page in extracted["pages"]:
        parts.append(f"=== Page {page['page_num']} ===")
        if page["tables"]:
            for ti, tbl in enumerate(page["tables"], start=1):
                parts.append(f"--- Table {ti} ---")
                for row in tbl:
                    parts.append(" | ".join(row))
        else:
            # No tables detected — use text fallback
            text = page["text"].strip()
            if text:
                parts.append("--- Page text (no tables detected) ---")
                parts.append(text)
        parts.append("")
    return "\n".join(parts)
