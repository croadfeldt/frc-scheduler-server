"""LLM client for parsing arbitrary schedule PDFs.

Targets any OpenAI-compatible chat-completions endpoint (vLLM, Anthropic,
OpenAI, Google, etc.). Configured via env vars:

    LLM_ENDPOINT — base URL ending in /v1, e.g. http://vllm-host:8000/v1
    LLM_MODEL    — model name as the server expects
    LLM_API_KEY  — optional, for endpoints that require auth

Backwards-compat: if LLM_ENDPOINT is unset but LLM_VISION_ENDPOINT (the
old separate-vision-endpoint config) is set, those values are used. This
lets existing deployments roll forward without secret edits.

Architecture note: this client used to maintain two separate endpoints
(text-only LLM for extracted text, vision LLM for page images). Empirically
the vision-capable models on the user's vLLM hardware (Qwen2.5-VL-7B-AWQ)
are FASTER for short structured-output tasks than the larger text-only
model on layer-split llama.cpp. So we now use one vision-capable endpoint
for both text-only prompts (day-plan extraction, schedule parsing from
extracted text) AND image prompts (vision strategy when text extraction
fails). One endpoint, one health check, one config block.

Sampling: pure greedy by default (temperature=0, top_p=1.0, no
repetition penalty). We rely on tight JSON Schema constraints (enum
on `kind`, regex pattern on time fields) to prevent the model from
emitting garbage even on confusing tabular inputs. The dedup pass in
pdf_dayplan handles the harmless case where greedy decoding produces
duplicate-but-valid blocks. All three sampler knobs are env-tunable
(LLM_TEMPERATURE, LLM_TOP_P, LLM_REPETITION_PENALTY) for live tuning.
Response is required to be strict JSON; we parse with tolerance for
common minor format issues (markdown code fences, leading prose).
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

log = logging.getLogger(__name__)


def _resolve_endpoint() -> tuple[str, str, str]:
    """Pick LLM endpoint config, preferring LLM_ENDPOINT but falling back to
    the legacy LLM_VISION_ENDPOINT vars so existing deployments work.

    Returns (endpoint, model, api_key) as strings; empty if neither set.
    """
    endpoint = os.getenv("LLM_ENDPOINT", "").rstrip("/")
    model    = os.getenv("LLM_MODEL", "")
    api_key  = os.getenv("LLM_API_KEY", "")
    if endpoint and model:
        return endpoint, model, api_key

    # Legacy fallback for deployments that still have the split-endpoint config
    legacy_ep = os.getenv("LLM_VISION_ENDPOINT", "").rstrip("/")
    legacy_md = os.getenv("LLM_VISION_MODEL", "")
    legacy_ak = os.getenv("LLM_VISION_API_KEY", "")
    if legacy_ep and legacy_md:
        return legacy_ep, legacy_md, legacy_ak

    return "", "", ""


# Capture once at import. Live env changes during a process aren't supported —
# pod restart is the right way to pick up new secrets.
LLM_ENDPOINT, LLM_MODEL, LLM_API_KEY = _resolve_endpoint()


# Timeout for structured-output calls. Vision-on-images can take 30-60s for
# multi-page schedules; text-only structured output usually finishes in <10s.
# 180s ceiling is "give up, the server is wedged."
LLM_TIMEOUT_SECONDS = 180.0

# Sampling knobs — tunable via env so bisecting causes of weird LLM
# behaviour (repetition loops, request rejections, malformed output)
# doesn't require a code change + redeploy.
#
# Defaults are pure greedy decoding (temperature=0, top_p=1.0, no
# repetition penalty). We tried temperature=0.1 + repetition_penalty=1.1
# to break repetition loops, but combined with a permissive schema this
# pushed the model into producing NON-repeating garbage (kind="20",
# times like "20:0") instead of the valid duplicate blocks the dedup
# pass already handles cleanly. Tightening the schema with enum +
# pattern constraints is the right knob for "must be valid"; greedy
# sampling + dedup is the right knob for "don't repeat".
def _envf(name: str, default: float) -> float:
    """Read a float env var, returning default on missing/empty/invalid."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default

LLM_TEMPERATURE        = _envf("LLM_TEMPERATURE",        0.0)
LLM_TOP_P              = _envf("LLM_TOP_P",              1.0)
# 1.0 = no penalty (omitted from request body). vLLM honours this
# OpenAI-extension parameter; some other backends may reject it.
LLM_REPETITION_PENALTY = _envf("LLM_REPETITION_PENALTY", 1.0)


def is_configured() -> bool:
    """True if LLM extraction is available."""
    return bool(LLM_ENDPOINT and LLM_MODEL)


# ── Prompts ──────────────────────────────────────────────────────────────────

# Match-list prompt for text-extracted PDF content (pdfplumber + OCR strategies).
TEXT_SYSTEM_PROMPT = """You are a JSON extraction tool. You are given the text content of an FRC qualification match schedule PDF. You must extract the match list as strict JSON.

Output schema (REQUIRED — your entire reply must be valid JSON matching this shape, with no other text):

{
  "format_detected": "<brief description of the schedule format you saw, e.g. 'MSHSL state schedule with column headers Match #, Time, Red 1...'>",
  "confidence": "<high|medium|low>",
  "matches": [
    {
      "match_num":      <int, 1-indexed>,
      "time":           "<HH:MM in 24-hour format, or empty string if not present>",
      "red":            [<red-1 team #>, <red-2 team #>, <red-3 team #>],
      "blue":           [<blue-1 team #>, <blue-2 team #>, <blue-3 team #>],
      "red_surrogate":  [<bool>, <bool>, <bool>],
      "blue_surrogate": [<bool>, <bool>, <bool>]
    }
  ],
  "notes": "<any concerns or ambiguities you noticed, or empty string>"
}

Rules:
1. Team numbers are positive integers. Never output strings or null for team numbers.
2. Surrogate flags identify "extra" matches that don't count toward ranking. Notations vary: italic text, asterisks (*), the letter S, parentheses (S), color highlighting. Match the notation to the team's POSITION in the alliance — if Red 1 is marked surrogate, set red_surrogate[0] = true.
3. Match numbers must be sequential starting from 1.
4. If you cannot confidently identify a value, set confidence to "low" and add a note explaining what was ambiguous. Never invent team numbers.
5. Convert all times to 24-hour HH:MM format. "10:30 AM" becomes "10:30". "1:30 PM" becomes "13:30".
6. Output JSON ONLY. No prose before or after. No markdown code fences. Just the JSON object.
"""


# Match-list prompt for image-input (vision strategy when text extraction
# returns nothing useful).
VISION_SYSTEM_PROMPT = """You are a JSON extraction tool. You are given one or more rendered pages of an FRC qualification match schedule. Read the pages carefully and extract the match list as strict JSON.

Output schema (REQUIRED — your entire reply must be valid JSON matching this shape, with no other text):

{
  "format_detected": "<brief description of the schedule format you saw>",
  "confidence": "<high|medium|low>",
  "matches": [
    {
      "match_num":      <int, 1-indexed>,
      "time":           "<HH:MM in 24-hour format, or empty string if not present>",
      "red":            [<red-1 team #>, <red-2 team #>, <red-3 team #>],
      "blue":           [<blue-1 team #>, <blue-2 team #>, <blue-3 team #>],
      "red_surrogate":  [<bool>, <bool>, <bool>],
      "blue_surrogate": [<bool>, <bool>, <bool>]
    }
  ],
  "notes": "<any concerns or ambiguities you noticed, or empty string>"
}

Rules:
1. Team numbers are positive integers. Read each digit carefully — schedules are dense and digit confusion (8/3, 0/6, 1/7) corrupts the schedule. If a digit is unclear, set confidence to "low" and note which match is ambiguous.
2. Schedules typically use columns like: Time, Match #, Red 1, Red 2, Red 3, Blue 1, Blue 2, Blue 3 (or Blue 1-3 then Red 1-3 — read the headers carefully).
3. Surrogate flags identify "extra" matches that don't count toward ranking. Notations vary: italic text, asterisks (*), the letter S, parentheses (S), color highlighting. Match the notation to the team's POSITION — if Red 1 is marked surrogate, set red_surrogate[0] = true.
4. Match numbers must be sequential starting from 1. Skip "Lunch" or break rows entirely; don't include them in the matches array.
5. Convert all times to 24-hour HH:MM format. "10:30 AM" becomes "10:30". "1:30 PM" becomes "13:30".
6. Output JSON ONLY. No prose before or after. No markdown code fences. Just the JSON object."""


def _build_text_user_prompt(pdf_text: str) -> str:
    return f"""Here is the extracted text from the schedule PDF. Extract the match list as JSON per the schema.

PDF CONTENT:
{pdf_text}

Output the JSON object now."""


def _parse_json_response(text: str) -> dict[str, Any]:
    """Tolerantly parse JSON out of an LLM response.

    Handles markdown code fences, leading prose, and trailing junk. Raises
    ValueError with diagnostic context if no parseable JSON can be found.

    On failure, the raised error includes a window around the parse error
    location (~150 chars before/after) so the user/operator can see what
    actually broke. The full response is also logged at WARNING level so
    pod logs have the complete payload for after-the-fact inspection.

    Common breakage modes from small structured-output models:
      - Trailing repetition: model gets stuck and re-emits the same array
        item until it hits max_tokens, leaving the JSON unclosed
      - Mid-stream drift: model switches to prose ("Here's another match…")
        partway through
      - Extra commas: trailing comma after the last array element
      - Smart quotes: typographic quotes instead of ASCII quotes
    """
    raw = text  # keep for diagnostics
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
    start = text.find("{")
    end   = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        log.warning(
            "LLM response had no JSON object. Full response (%d chars):\n%s",
            len(raw), raw[:4000],
        )
        raise ValueError(
            "No JSON object found in LLM response. "
            f"First 200 chars: {raw[:200]!r}"
        )
    candidate = text[start:end + 1]

    # First attempt: parse as-is
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        first_err = e

    # Second attempt: strip trailing commas before } or ]. Some models add
    # them despite the "valid JSON" instruction.
    repaired = re.sub(r",(\s*[}\]])", r"\1", candidate)
    if repaired != candidate:
        try:
            log.info("First JSON parse failed; retrying with trailing commas stripped")
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

    # Third attempt: replace smart quotes with ASCII quotes
    smart_fixed = (
        candidate
        .replace("\u201c", '"').replace("\u201d", '"')
        .replace("\u2018", "'").replace("\u2019", "'")
    )
    if smart_fixed != candidate:
        try:
            log.info("First JSON parse failed; retrying with smart quotes normalized")
            return json.loads(smart_fixed)
        except json.JSONDecodeError:
            pass

    # All repairs failed. Surface a useful error: show where the parser
    # gave up + a window of surrounding content. We deliberately show
    # MORE of what comes AFTER the failure than before, because the
    # before-context is usually correct JSON; the bug is what comes
    # next. Common cases: missing comma, extra `{`, prose drift,
    # truncation (response just stops mid-string).
    pos = first_err.pos if hasattr(first_err, "pos") else 0
    window_start = max(0, pos - 80)
    window_end   = min(len(candidate), pos + 220)
    before = candidate[window_start:pos]
    at_and_after = candidate[pos:window_end]

    # Detect truncation: did the response stop without a closing }?
    # If candidate doesn't end with } at the top level, we got cut off.
    # This happens when max_tokens is hit mid-output OR when the model
    # emits an EOS that the grammar doesn't allow but vLLM honors anyway.
    truncation_likely = (
        not candidate.rstrip().endswith("}")
        or pos >= len(candidate) - 5  # error within last 5 chars
    )

    log.warning(
        "LLM JSON parse failed at position %d/%d. Full response:\n%s",
        pos, len(candidate), raw,
    )

    diagnostic = (
        f"Invalid JSON from LLM: {first_err.msg} at char {pos}. "
        f"Before: ...{before!r} "
        f"At/after: {at_and_after!r}..."
    )
    if truncation_likely:
        diagnostic += (
            " [Looks like the response was TRUNCATED — the model stopped "
            "mid-output. Check vLLM logs and consider raising max_tokens "
            "or simplifying the input.]"
        )
    diagnostic += f" Total response length: {len(raw)} chars."

    raise ValueError(diagnostic)


# ── JSON schemas (for vLLM guided_json structured output) ────────────────────
# These describe the *shape* the model is asked to produce. When passed to
# vLLM via guided_json, the decoder enforces the structure at sampling time —
# the model literally cannot emit invalid JSON or wrong-typed fields. This
# is critical for small models (7B class) which otherwise drift, repeat,
# or trail off on multi-field structured tasks.
#
# Schema philosophy:
#   - Keep schemas as PERMISSIVE as possible while still catching the shape
#     errors that break downstream code. Over-strict schemas (regex-validated
#     time strings, enums for every label) make decoding harder and slower
#     and can cause vLLM to refuse to terminate.
#   - Use `additionalProperties: true` so the model can include fields we
#     didn't anticipate without crashing the decoder.
#   - Don't enumerate `required` for nice-to-have fields; the adapter
#     handles missing keys gracefully.

MATCH_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "format_detected": {"type": "string"},
        "confidence":      {"type": "string"},
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "match_num":      {"type": "integer"},
                    # Time may be missing in some PDFs. Schema allows empty
                    # string; downstream adapter treats "" as "no time".
                    # NOTE: vLLM's structured-output parser doesn't accept
                    # array-typed type fields like ["string", "null"], so
                    # we use plain "string" with empty-string-as-absent.
                    "time":           {"type": "string"},
                    "red":            {"type": "array", "items": {"type": "integer"}},
                    "blue":           {"type": "array", "items": {"type": "integer"}},
                    "red_surrogate":  {"type": "array", "items": {"type": "boolean"}},
                    "blue_surrogate": {"type": "array", "items": {"type": "boolean"}},
                },
                "required": ["match_num", "red", "blue"],
                # NOTE: do NOT set additionalProperties: True. xgrammar
                # (vLLM's structured-output backend) crashes during
                # grammar compilation on some additionalProperties
                # constructs with an opaque 500. By default JSON Schema
                # allows extras when not specified, so omitting the key
                # gives us the same flexibility without tripping the bug.
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["matches"],
}

DAYPLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "format_detected": {"type": "string"},
        "confidence":      {"type": "string"},
        "event_dates": {
            "type": "object",
            "properties": {
                # YYYY-MM-DD or empty if no date in the PDF. vLLM's schema
                # parser doesn't handle ["string", "null"] union types
                # (raises "type mismatch! call is<type>() before get<type>()"
                # because it expects "type" to be a string scalar).
                "start": {"type": "string"},
                "end":   {"type": "string"},
            },
        },
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    # ENUM is critical here. Without it, the model can
                    # emit any string for kind ("20", "abc", "Saturday",
                    # gibberish) and the schema accepts it. With small
                    # models on tabular inputs and any non-greedy
                    # sampling, the kind field is the most common
                    # source of garbage. xgrammar enforces enum at
                    # decode time — the model literally cannot pick
                    # an invalid token.
                    "kind": {
                        "type": "string",
                        "enum": [
                            "practice", "qual", "lunch", "break",
                            "ceremony", "playoff",
                        ],
                    },
                    "day_index": {"type": "integer"},
                    # HH:MM 24-hour format, OR empty string when the PDF
                    # gives only a start time (e.g. "Playoffs Begin
                    # 4:00 PM" has no end). Pattern enforces the
                    # format at decode time so the model can't emit
                    # "20:0" or "8 AM" or other almost-valid garbage.
                    # Adapter handles "" the same as missing.
                    "start": {
                        "type": "string",
                        "pattern": "^([01][0-9]|2[0-3]):[0-5][0-9]$|^$",
                    },
                    "end": {
                        "type": "string",
                        "pattern": "^([01][0-9]|2[0-3]):[0-5][0-9]$|^$",
                    },
                    "label":   {"type": "string"},
                    "details": {"type": "string"},
                },
                "required": ["kind", "day_index"],
            },
        },
        "raw_phases": {
            "type": "array",
            "items": {"type": "object"},
        },
        "notes": {"type": "string"},
    },
    "required": ["blocks"],
}


# ── Core call ────────────────────────────────────────────────────────────────

async def _post(messages: list[dict[str, Any]], *,
                max_tokens: int = 8000,
                json_schema: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send a chat-completion request and return the parsed JSON content.

    All structured-extraction call sites go through this. Centralizes the
    timeout, error-handling, and JSON-tolerant parsing.

    json_schema (optional): when provided, constrains the model to produce
    output that conforms to the schema. This is vLLM's `guided_json`
    feature — at decode time vLLM masks tokens that would violate the
    schema, so the response is GUARANTEED to be syntactically valid JSON
    matching the structure (assuming sufficient max_tokens). Other OpenAI-
    compatible backends ignore the field harmlessly. This is the right
    tool for small-model structured-output drift; without it, models
    sometimes trail off, repeat themselves, or generate prose mid-output.
    """
    if not is_configured():
        raise RuntimeError("LLM not configured (set LLM_ENDPOINT and LLM_MODEL)")

    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"

    body: dict[str, Any] = {
        "model":       LLM_MODEL,
        "messages":    messages,
        "max_tokens":  max_tokens,
        # Greedy decoding by default. We rely on tight schema constraints
        # (enum on kind, regex pattern on times) to prevent the model
        # from emitting garbage values, and on the dedup pass in
        # pdf_dayplan to handle the case where greedy decoding produces
        # duplicate-but-valid blocks. Tunable via LLM_TEMPERATURE /
        # LLM_TOP_P env vars.
        "temperature": LLM_TEMPERATURE,
        "top_p":       LLM_TOP_P,
    }
    # Only include repetition_penalty if it's actually penalizing.
    # 1.0 = no penalty; vLLM accepts it as an OpenAI extension but
    # other backends may reject it. Off by default — turning it on
    # without tightening the schema first pushes the model into
    # NON-repeating garbage output.
    if abs(LLM_REPETITION_PENALTY - 1.0) > 0.001:
        body["repetition_penalty"] = LLM_REPETITION_PENALTY
    if json_schema is not None:
        # vLLM's structured-output spec. The "guided_json" key takes a
        # JSON Schema and the decoder enforces it — output is guaranteed
        # to be syntactically valid JSON matching the structure (assuming
        # sufficient max_tokens). Documented at:
        # https://docs.vllm.ai/en/latest/features/structured_outputs.html
        #
        # NOTE: do NOT also set response_format={"type": "json_object"}.
        # vLLM treats both as guided-decoding modes and rejects with
        # "you can only use one kind of guided decoding" when both are
        # present. guided_json is strictly stronger (it's schema-enforced
        # vs. just "must be JSON object"), so it's the right choice.
        body["guided_json"] = json_schema

    url = f"{LLM_ENDPOINT}/chat/completions"
    log.info(
        "Calling LLM at %s (model=%s, max_tokens=%d, guided=%s)",
        url, LLM_MODEL, max_tokens, "yes" if json_schema else "no",
    )

    async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
        try:
            r = await client.post(url, json=body, headers=headers)
            r.raise_for_status()
        except httpx.TimeoutException:
            raise RuntimeError(
                f"LLM timed out after {LLM_TIMEOUT_SECONDS}s. The endpoint may "
                f"be queued behind another workload, loading a cold model, "
                f"or wedged. Try again or check the inference server logs."
            )
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"LLM returned {e.response.status_code}: {e.response.text[:300]}"
            )
        except httpx.RequestError as e:
            raise RuntimeError(f"LLM unreachable: {e}")

        data = r.json()

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Unexpected LLM response shape: {json.dumps(data)[:500]}")

    if not content or not content.strip():
        raise RuntimeError("LLM returned empty response")

    return _parse_json_response(content)


# ── Public API: schedule extraction (text or image input) ────────────────────

async def parse_schedule(pdf_text: str) -> dict[str, Any] | None:
    """Send extracted PDF text to the LLM, return parsed schedule dict.

    Returns None if not configured. Raises RuntimeError on extraction
    failures (timeout, network, malformed response).
    """
    if not is_configured():
        return None

    return await _post(
        messages=[
            {"role": "system", "content": TEXT_SYSTEM_PROMPT},
            {"role": "user",   "content": _build_text_user_prompt(pdf_text)},
        ],
        # Match-list output for a 92-match schedule is roughly 8K tokens of JSON
        max_tokens=16000,
        json_schema=MATCH_LIST_SCHEMA,
    )


def _image_to_data_url(img) -> str:
    """Convert a Pillow Image to a data: URL the OpenAI vision API accepts.

    Encoded as JPEG (smaller than PNG, fine for tabular schedules at 150 DPI).
    """
    import base64
    import io as _io

    buf = _io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=90)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


async def parse_schedule_from_images(images: list) -> dict[str, Any] | None:
    """Send rasterized PDF pages to the LLM (which must be vision-capable),
    return parsed schedule dict.

    Returns None if not configured. Raises on extraction failures.
    """
    if not is_configured():
        return None
    if not images:
        raise RuntimeError("No images supplied")

    user_content: list[dict[str, Any]] = []
    for idx, img in enumerate(images, start=1):
        user_content.append({"type": "text", "text": f"Page {idx}:"})
        user_content.append({
            "type": "image_url",
            "image_url": {"url": _image_to_data_url(img)},
        })
    user_content.append({
        "type": "text",
        "text": (
            "Extract the qualification match list as JSON per the schema. "
            "Output the JSON object now."
        ),
    })

    return await _post(
        messages=[
            {"role": "system", "content": VISION_SYSTEM_PROMPT},
            {"role": "user",   "content": user_content},
        ],
        max_tokens=16000,
        json_schema=MATCH_LIST_SCHEMA,
    )


# ── Health check ─────────────────────────────────────────────────────────────

async def health_check() -> dict[str, Any]:
    """Probe the LLM endpoint and return availability status.

    Used by /api/llm/status to surface availability to the UI. vLLM and
    llama.cpp both expose /health at server root (NOT /v1/health), so we
    strip /v1 from the configured endpoint and probe the parent host.
    """
    if not is_configured():
        return {"configured": False, "available": False}

    base = LLM_ENDPOINT.rsplit("/v1", 1)[0] if LLM_ENDPOINT.endswith("/v1") else LLM_ENDPOINT
    health_url = f"{base}/health"

    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            r = await client.get(health_url)
            return {
                "configured": True,
                "available":  r.status_code == 200,
                "endpoint":   LLM_ENDPOINT,
                "model":      LLM_MODEL,
            }
        except httpx.RequestError as e:
            return {
                "configured": True,
                "available":  False,
                "endpoint":   LLM_ENDPOINT,
                "model":      LLM_MODEL,
                "error":      str(e),
            }
