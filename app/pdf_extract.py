"""PDF schedule extraction — multi-strategy router.

PDFs come in three structural shapes that need different extraction approaches:

  1. **Text-native** PDFs (most FIRST official schedules): real text data
     with positioning. pdfplumber's table reconstruction works well.
  2. **Image-based** PDFs (MSHSL state, many off-season events, anything
     scanned or "saved as PDF" from an image): a raster image is embedded;
     no extractable text. Tesseract OCR turns the image back into text we
     can feed the LLM.
  3. **Mixed or weird-layout** PDFs: text with rotated/multi-column/
     stylized layouts, or where TableFormer-style structure recovery
     matters. Vision-capable LLM directly interprets rasterized pages.

The router tries strategies in cost order: native (free, fast) → OCR
(free, ~1-3s/page) → vision (slower, uses GPU). First strategy with
useful output wins.

Output shape (returned from `extract_schedule()`):
    {
        "strategy":   "native" | "ocr" | "vision",
        "page_count": int,
        "byte_size":  int,
        # For native/OCR strategies: structured text the text-LLM consumes
        "text":       str | None,          # set for native + ocr
        "tables":     list | None,         # set for native (pdfplumber)
        # For vision strategy: parsed JSON directly from the vision LLM
        "parsed":     dict | None,         # set for vision; replaces text+tables
        # Diagnostics for the UI / logs
        "tried":      list[str],           # which strategies fired and what happened
    }

The endpoint glue in main.py decides whether to call the text LLM (when
`text` is present) or skip straight to using the vision LLM's output
(when `parsed` is present).
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
from typing import Any

import pdfplumber

log = logging.getLogger(__name__)

# Cap PDFs at a reasonable size. Beyond this is almost certainly misuse —
# a 50-page document for a 92-match event would be ~5MB max. Stops memory
# exhaustion attacks via gigantic PDFs.
MAX_PDF_BYTES = 10 * 1024 * 1024   # 10 MB
# Cap pages because some PDFs have hundreds of decorative pages.
# A typical schedule PDF is 1-8 pages.
MAX_PAGES = 30

# Below this many extracted characters per page, we treat the native
# extraction as having failed and fall through to OCR. Tuned empirically:
# the MSHSL PDF returns ~50 chars (just the header), a real schedule
# returns 2000+ chars per page.
NATIVE_MIN_CHARS_PER_PAGE = 200

# DPI for rasterizing pages for OCR. 300 gives Tesseract solid digit
# accuracy on dense tabular schedules. Higher costs more memory; lower
# costs accuracy. 300 is the standard "high quality OCR" default.
OCR_DPI = 300

# DPI for rasterizing pages to send to a vision LLM. Vision models will
# downsample anyway; 150 is plenty and keeps payload small.
VISION_DPI = 150


def hash_pdf(content: bytes) -> str:
    """Return SHA-256 hex digest of PDF bytes — used as cache key.

    Same bytes → same hash → same parsed result, regardless of filename
    or which extraction strategy fired.
    """
    return hashlib.sha256(content).hexdigest()


# ── Strategy 1: native text extraction (pdfplumber) ──────────────────────────

def _extract_native(content: bytes) -> dict[str, Any] | None:
    """Try pdfplumber's table-aware extraction.

    Returns a dict with text + tables on success. Returns None if the PDF
    appears to have no extractable text (image-based PDF) — caller falls
    through to OCR.
    """
    pages_out: list[dict[str, Any]] = []
    total_chars = 0

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        page_count = len(pdf.pages)
        if page_count > MAX_PAGES:
            raise ValueError(f"PDF too long: {page_count} pages (max {MAX_PAGES})")

        for i, page in enumerate(pdf.pages, start=1):
            try:
                raw_tables = page.extract_tables() or []
            except Exception as e:
                log.warning("Native: table extraction failed page %d: %s", i, e)
                raw_tables = []

            tables_norm = []
            for tbl in raw_tables:
                rows = []
                for row in tbl:
                    cells = [c.strip() if c else "" for c in row]
                    if any(cells):
                        rows.append(cells)
                if rows:
                    tables_norm.append(rows)

            try:
                text = (page.extract_text() or "").strip()
            except Exception as e:
                log.warning("Native: text extraction failed page %d: %s", i, e)
                text = ""

            total_chars += len(text)
            pages_out.append({"page_num": i, "tables": tables_norm, "text": text})

        meta = pdf.metadata or {}

    # Decide if native extraction produced anything useful. If the average
    # per-page character count is below threshold, this is almost certainly
    # an image-based PDF — fall through to OCR.
    avg_chars = total_chars / max(page_count, 1)
    if avg_chars < NATIVE_MIN_CHARS_PER_PAGE:
        log.info(
            "Native extraction looks empty (%.0f chars/page, threshold %d). "
            "Falling through to OCR.",
            avg_chars, NATIVE_MIN_CHARS_PER_PAGE,
        )
        return None

    return {
        "page_count": page_count,
        "pages":      pages_out,
        "metadata":   {
            "title":   meta.get("Title", ""),
            "author":  meta.get("Author", ""),
            "creator": meta.get("Creator", ""),
            "subject": meta.get("Subject", ""),
        },
        "byte_size":  len(content),
    }


# ── Strategy 2: OCR (Tesseract on rasterized pages) ──────────────────────────

def _rasterize_pages(content: bytes, dpi: int) -> list:
    """Rasterize each PDF page to a Pillow Image. Returns list of Images.

    Lazy-imports pdfplumber's pillow conversion path so we don't pay the
    Pillow cost when only native extraction is needed.
    """
    pages = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            # pdfplumber.Page.to_image returns a wrapper; .original is PIL.Image
            img = page.to_image(resolution=dpi).original
            pages.append(img)
    return pages


def _ocr_page_with_layout(img, pytesseract) -> str:
    """OCR a single page image, preserving the visual row structure.

    The naive `image_to_string` approach has a known weakness on wide
    tabular layouts: depending on PSM mode, Tesseract either reads
    column-by-column (missing the right side of wide tables) or skips
    rows entirely. We work around this by:

    1. Calling `image_to_data` (PSM 11 = sparse text, find everything)
       to get every word with x/y coordinates.
    2. Clustering words by y-position into "visual rows" — words within
       ~25px of each other vertically belong to the same row.
    3. Sorting each row's words left-to-right and joining with spaces.

    This produces clean per-row text that mirrors what a human reads,
    regardless of how wide the table is. Empirically captures all 42
    qualification rows × 6 team numbers in the MSHSL state schedule;
    PSM 4/6 either cut off the right columns or skipped rows.

    Some OCR errors (digit confusion, e.g. 5→9) are unavoidable and the
    LLM is expected to catch these via roster cross-check.
    """
    # Extract word positions
    data = pytesseract.image_to_data(
        img, config="--psm 11", output_type=pytesseract.Output.DICT
    )
    words = []
    for i in range(len(data["text"])):
        text = (data["text"][i] or "").strip()
        conf = data["conf"][i]
        # Filter low-confidence noise (Tesseract reports -1 for non-text regions)
        if not text or conf is None or (isinstance(conf, (int, float)) and conf < 30):
            continue
        words.append({
            "text": text,
            "left": data["left"][i],
            "top":  data["top"][i],
        })

    if not words:
        return ""

    # Cluster by y-position. Sort by top then left, then start a new row
    # whenever the y-gap exceeds the row threshold.
    words.sort(key=lambda w: (w["top"], w["left"]))

    # Adaptive row threshold: median word height × 1.5. For 300 DPI
    # rendering of a 12pt font, words are ~30-40px tall, so threshold
    # ends up around 45px — large enough to keep a row together, small
    # enough to split between rows.
    heights = [data["height"][i] for i in range(len(data["text"]))
               if data["text"][i] and data["text"][i].strip()]
    median_h = sorted(heights)[len(heights) // 2] if heights else 30
    row_threshold = max(20, int(median_h * 1.5))

    rows: list[list[dict]] = []
    current: list[dict] = []
    last_top = None
    for w in words:
        if last_top is None or abs(w["top"] - last_top) <= row_threshold:
            current.append(w)
        else:
            if current:
                rows.append(current)
            current = [w]
        last_top = w["top"]
    if current:
        rows.append(current)

    # Sort each row left-to-right and join
    lines = []
    for row in rows:
        row.sort(key=lambda w: w["left"])
        lines.append(" ".join(w["text"] for w in row))
    return "\n".join(lines)


def _extract_ocr(content: bytes) -> dict[str, Any] | None:
    """OCR each page with Tesseract. Returns extracted text per page.

    Returns None if pytesseract isn't installed (graceful degradation —
    OCR is optional). Raises if Tesseract is installed but fails on the
    actual image.
    """
    try:
        import pytesseract
    except ImportError:
        log.info("OCR strategy unavailable: pytesseract not installed")
        return None

    pages_out: list[dict[str, Any]] = []
    total_chars = 0

    images = _rasterize_pages(content, OCR_DPI)
    page_count = len(images)

    for i, img in enumerate(images, start=1):
        try:
            text = _ocr_page_with_layout(img, pytesseract).strip()
        except pytesseract.TesseractNotFoundError:
            log.warning("OCR strategy unavailable: tesseract binary not in PATH")
            return None
        except Exception as e:
            log.warning("OCR failed on page %d: %s", i, e)
            text = ""

        total_chars += len(text)
        pages_out.append({"page_num": i, "tables": [], "text": text})

    if total_chars < NATIVE_MIN_CHARS_PER_PAGE:
        log.info("OCR produced almost no text — likely a blank or image-only PDF")
        return None

    return {
        "page_count": page_count,
        "pages":      pages_out,
        "metadata":   {},
        "byte_size":  len(content),
    }


# ── Strategy 3: Vision LLM (rasterize → send images to vLLM) ────────────────

async def _extract_vision(content: bytes) -> dict[str, Any] | None:
    """Send rasterized pages to a vision-capable LLM endpoint.

    Returns None if LLM_VISION_ENDPOINT isn't configured (caller treats
    vision as an unavailable strategy). On success, returns a parsed
    schedule dict in the same shape as llm_client.parse_schedule()'s
    output — not a text+tables payload.
    """
    if not os.getenv("LLM_VISION_ENDPOINT", "").strip():
        log.info("Vision strategy unavailable: LLM_VISION_ENDPOINT not configured")
        return None

    # Lazy import to keep llm_client decoupled from extraction in tests
    from app import llm_client

    images = _rasterize_pages(content, VISION_DPI)
    page_count = len(images)

    parsed = await llm_client.parse_schedule_from_images(images)
    if parsed is None:
        return None

    return {
        "page_count": page_count,
        "pages":      [],         # vision returns parsed JSON, no per-page text
        "metadata":   {},
        "byte_size":  len(content),
        "parsed":     parsed,     # signals the endpoint to skip text-LLM step
    }


# ── Public router ────────────────────────────────────────────────────────────

async def extract_schedule(content: bytes) -> dict[str, Any]:
    """Run extraction strategies in order, return first success.

    Order: native → OCR → vision. Each strategy's failure is logged into
    `tried` so the UI/error message can show what was attempted.
    """
    if len(content) > MAX_PDF_BYTES:
        raise ValueError(f"PDF too large: {len(content)} bytes (max {MAX_PDF_BYTES})")

    tried: list[dict[str, str]] = []

    # Strategy 1: native
    try:
        native = _extract_native(content)
    except ValueError:
        # Page-count guard etc. — propagate
        raise
    except Exception as e:
        log.warning("Native strategy raised: %s", e)
        tried.append({"strategy": "native", "result": "error", "detail": str(e)[:200]})
        native = None
    if native is not None:
        return {
            "strategy":   "native",
            "page_count": native["page_count"],
            "byte_size":  native["byte_size"],
            "pages":      native["pages"],
            "metadata":   native["metadata"],
            "tried":      tried + [{"strategy": "native", "result": "success"}],
        }
    else:
        tried.append({"strategy": "native", "result": "empty"})

    # Strategy 2: OCR
    try:
        ocr = await asyncio.to_thread(_extract_ocr, content)
    except Exception as e:
        log.warning("OCR strategy raised: %s", e)
        tried.append({"strategy": "ocr", "result": "error", "detail": str(e)[:200]})
        ocr = None
    if ocr is not None:
        return {
            "strategy":   "ocr",
            "page_count": ocr["page_count"],
            "byte_size":  ocr["byte_size"],
            "pages":      ocr["pages"],
            "metadata":   ocr["metadata"],
            "tried":      tried + [{"strategy": "ocr", "result": "success"}],
        }
    else:
        # Distinguish "OCR not installed" from "OCR ran and produced nothing".
        # Both look like None to the caller; the log line above tells us which.
        tried.append({"strategy": "ocr", "result": "empty_or_unavailable"})

    # Strategy 3: vision
    try:
        vision = await _extract_vision(content)
    except Exception as e:
        log.warning("Vision strategy raised: %s", e)
        tried.append({"strategy": "vision", "result": "error", "detail": str(e)[:200]})
        vision = None
    if vision is not None:
        return {
            "strategy":   "vision",
            "page_count": vision["page_count"],
            "byte_size":  vision["byte_size"],
            "pages":      [],
            "metadata":   vision["metadata"],
            "parsed":     vision["parsed"],     # already-parsed schedule JSON
            "tried":      tried + [{"strategy": "vision", "result": "success"}],
        }
    else:
        tried.append({"strategy": "vision", "result": "unavailable_or_empty"})

    # All strategies exhausted
    raise ValueError(
        "Could not extract schedule from PDF. Tried: "
        + ", ".join(f"{t['strategy']}={t['result']}" for t in tried)
    )


# ── Backwards-compat: keep extract_tables for any code still calling it ─────

def extract_tables(content: bytes) -> dict[str, Any]:
    """Legacy synchronous extraction. Returns the native-strategy shape only.

    Code that depends on this should migrate to extract_schedule() which
    is the new strategy-router entry point. Kept for now to avoid a
    flag-day rewrite of unrelated callers.
    """
    if len(content) > MAX_PDF_BYTES:
        raise ValueError(f"PDF too large: {len(content)} bytes (max {MAX_PDF_BYTES})")
    native = _extract_native(content)
    if native is None:
        # Old behavior was to return whatever pdfplumber produced even if
        # it was empty. Match that — empty pages list, zero text.
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            page_count = len(pdf.pages)
        return {
            "page_count": page_count,
            "pages":      [{"page_num": i, "tables": [], "text": ""} for i in range(1, page_count + 1)],
            "metadata":   {},
            "byte_size":  len(content),
        }
    return native


def estimate_token_budget(extracted: dict[str, Any]) -> int:
    """Rough token estimate for the LLM payload. Used to refuse PDFs that
    would exceed the context window. Roughly 4 chars per token for English.

    Vision strategy bypasses this — its output is already-parsed JSON, so
    no further LLM call is needed. Returns 0 for vision-strategy results.
    """
    if extracted.get("strategy") == "vision":
        return 0

    total_chars = 0
    for page in extracted.get("pages", []):
        for tbl in page.get("tables", []):
            for row in tbl:
                total_chars += sum(len(c) for c in row) + len(row) * 2
        total_chars += len(page.get("text", ""))
    return total_chars // 4 + 2000


def format_for_llm(extracted: dict[str, Any]) -> str:
    """Format the extracted tables/text for inclusion in a text-LLM prompt.

    Tables are rendered as pipe-delimited rows (markdown-table style) —
    LLMs handle that format reliably. Text fallback is appended verbatim.

    Vision-strategy results don't go through this path because they're
    already-parsed JSON, not text to interpret.
    """
    parts: list[str] = []
    for page in extracted.get("pages", []):
        parts.append(f"=== Page {page['page_num']} ===")
        if page.get("tables"):
            for ti, tbl in enumerate(page["tables"], start=1):
                parts.append(f"--- Table {ti} ---")
                for row in tbl:
                    parts.append(" | ".join(row))
        else:
            text = page.get("text", "").strip()
            if text:
                parts.append("--- Page text (no tables detected) ---")
                parts.append(text)
        parts.append("")
    return "\n".join(parts)
