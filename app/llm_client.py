"""LLM client for parsing arbitrary schedule PDFs.

Targets any OpenAI-compatible endpoint (vLLM, llama.cpp's llama-server,
Anthropic API, OpenAI, etc.). Configured via env vars:

    LLM_ENDPOINT   — base URL, e.g. http://vis.example.com:8000/v1
    LLM_MODEL      — model name as the server expects, e.g. "qwen"
    LLM_API_KEY    — optional, for endpoints that require auth

When LLM_ENDPOINT is empty, the parse_schedule() function returns None
and callers fall back to deterministic format-specific parsers.

Implementation notes specific to llama.cpp + Qwen3 (the primary target):

- All sampling params must be EXPLICIT. The server has CLI defaults
  (top_k=1, temperature=0) that act as a "greedy fallback" when body
  params are unspecified. We always send the full set so we never
  accidentally inherit the wrong defaults.
- We use Mode 2 (cache-accelerated greedy) per the endpoint doc:
  temperature=0, top_k=1, cache_prompt=true, enable_thinking=false.
  Determinism + speed for repeated prefixes.
- We don't rely on tool calling — Qwen3 + llama.cpp's tool support is
  newer and varies. Instead, we prompt for strict JSON output and
  parse + validate in Python.
- thinking is disabled because it consumes max_tokens budget on
  schedules where we don't need reasoning.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

import httpx

log = logging.getLogger(__name__)

LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "").rstrip("/")
LLM_MODEL    = os.getenv("LLM_MODEL", "")
LLM_API_KEY  = os.getenv("LLM_API_KEY", "")

# How long to wait for the LLM. Schedules can take 30-60s to extract on
# a single-parallel endpoint, especially if other workloads are queued.
# Anything beyond 3 minutes is probably stuck and we should give up.
LLM_TIMEOUT_SECONDS = 180.0


def is_configured() -> bool:
    """True if LLM extraction is available."""
    return bool(LLM_ENDPOINT and LLM_MODEL)


# Prompt — kept stable across calls so cache_prompt has a consistent prefix.
# Putting the schema definition before the variable PDF content lets the
# server's KV cache reuse most of the prompt across requests.
SYSTEM_PROMPT = """You are a JSON extraction tool. You are given the text content of an FRC qualification match schedule PDF. You must extract the match list as strict JSON.

Output schema (REQUIRED — your entire reply must be valid JSON matching this shape, with no other text):

{
  "format_detected": "<brief description of the schedule format you saw, e.g. 'MSHSL state schedule with column headers Match #, Time, Red 1...'>",
  "confidence": "<high|medium|low>",
  "matches": [
    {
      "match_num":      <int, 1-indexed>,
      "time":           "<HH:MM in 24-hour format, or null if not present>",
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


def build_user_prompt(pdf_text: str) -> str:
    """The variable part of the prompt — only this changes between requests,
    so the cache_prompt prefix stays warm for the system prompt and schema.
    """
    return f"""Here is the extracted text from the schedule PDF. Extract the match list as JSON per the schema.

PDF CONTENT:
{pdf_text}

Output the JSON object now."""


def _parse_json_response(text: str) -> dict[str, Any]:
    """Parse the LLM's response, tolerating common minor format issues
    (markdown code fences, leading/trailing whitespace, "Here is the JSON..." preamble).

    Raises ValueError if no valid JSON can be extracted.
    """
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        # Remove leading ```json or ```
        text = re.sub(r"^```(?:json)?\s*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
    # Some models prepend prose despite instructions. Find first { and last }.
    start = text.find("{")
    end   = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in LLM response")
    candidate = text[start:end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON from LLM: {e}")


async def parse_schedule(pdf_text: str) -> dict[str, Any] | None:
    """Send extracted PDF text to the LLM, return parsed schedule dict.

    Returns None if LLM is not configured. Raises on actual extraction
    failures (timeout, network error, malformed response).
    """
    if not is_configured():
        return None

    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"

    body = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": build_user_prompt(pdf_text)},
        ],
        # Enough room for the schema + ~120 matches. JSON is verbose; a
        # 92-match schedule serializes to roughly 8K tokens of output.
        "max_tokens": 16000,
        # Mode 2 (cache-accelerated greedy) per endpoint doc — we want
        # deterministic outputs but with KV cache reuse for the system
        # prompt prefix across requests.
        "temperature": 0,
        "top_p":       1.0,
        # llama.cpp-specific knobs. The OpenAI Python SDK calls these
        # extra_body; via raw httpx we just put them at the top level.
        "top_k":         1,
        "min_p":         0.0,
        "seed":          42,
        "cache_prompt":  True,
        "chat_template_kwargs": {"enable_thinking": False},
    }

    url = f"{LLM_ENDPOINT}/chat/completions"
    log.info("Calling LLM endpoint %s with model %s", url, LLM_MODEL)

    async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
        try:
            r = await client.post(url, json=body, headers=headers)
            r.raise_for_status()
        except httpx.TimeoutException:
            raise RuntimeError(
                f"LLM endpoint timed out after {LLM_TIMEOUT_SECONDS}s. The server may be "
                f"queued behind another workload. Try again in a minute."
            )
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"LLM endpoint returned {e.response.status_code}: {e.response.text[:200]}")
        except httpx.RequestError as e:
            raise RuntimeError(f"LLM endpoint unreachable: {e}")

        data = r.json()

    # Standard OpenAI completion shape
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Unexpected LLM response shape: {json.dumps(data)[:500]}")

    if not content or not content.strip():
        # llama.cpp will sometimes return empty content if thinking consumed
        # the budget — even though we set enable_thinking=false. Check
        # reasoning_content as a fallback.
        try:
            reasoning = data["choices"][0]["message"].get("reasoning_content", "")
            if reasoning and reasoning.strip():
                content = reasoning
        except Exception:
            pass

    if not content or not content.strip():
        raise RuntimeError("LLM returned empty response")

    return _parse_json_response(content)


async def health_check() -> dict[str, Any]:
    """Probe the LLM endpoint's /health (or equivalent) and return a status dict.

    Used by /api/health to surface LLM availability to the UI without making
    a real extraction call.
    """
    if not is_configured():
        return {"configured": False, "available": False}

    # llama.cpp exposes /health (NOT /v1/health) — probe the parent host
    base = LLM_ENDPOINT.rsplit("/v1", 1)[0] if LLM_ENDPOINT.endswith("/v1") else LLM_ENDPOINT
    health_url = f"{base}/health"
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            r = await client.get(health_url)
            ok = r.status_code == 200
            return {
                "configured": True,
                "available":  ok,
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
