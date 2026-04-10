"""
LLM reconciliation layer for the polycr router.

Why: Multiple OCR engines produce divergent outputs; an LLM with vision can compare
     all outputs side-by-side and produce a single high-confidence transcription plus
     structured field extraction, which no single OCR engine can do reliably on its own.
What: Sends all engine results plus the preprocessed image (as base64) to the configured
      LLM provider and parses the returned JSON into {"text": str, "structured": dict}.
Test: Mock the HTTP client to return a valid JSON string; assert reconcile() returns a
      dict with "text" and "structured" keys.  Pass a response wrapped in ```json fences
      and assert the fence is stripped correctly.
"""

import base64
import json
import logging
import os
import re
from typing import Any

import httpx

from models import EngineResult

logger = logging.getLogger(__name__)

_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
_API_KEY = os.getenv("LLM_API_KEY", "")
_MODEL = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")

_SYSTEM_PROMPT = (
    "You are an expert OCR post-processor. You will receive the raw output of several "
    "OCR engines and an image. Reconcile the outputs into the single most accurate "
    "transcription. Then extract any structured fields you can find in the text, such as: "
    "dates, times, names, locations, phone numbers, email addresses, URLs, prices, invoice "
    "numbers, order IDs, RSVP details, and any other clearly labelled values. "
    "Reply with ONLY valid JSON in this exact format (no prose, no markdown fences): "
    '{"text": "<reconciled full text>", "structured": {<extracted fields as key:value>}}'
)

_FALLBACK_RESULT: dict[str, Any] = {"text": "", "structured": {}}


async def reconcile(results: list[EngineResult], image_bytes: bytes) -> dict[str, Any]:
    """
    Why: Routes reconciliation to the correct provider-specific function based on the
         LLM_PROVIDER env var, keeping individual provider implementations isolated.
    What: Dispatches to anthropic/openai/openrouter/groq handler; on any failure falls
          back to the best-confidence engine result so the pipeline never returns empty.
    Test: Set LLM_PROVIDER=anthropic and mock _call_anthropic to return valid JSON;
          assert reconcile() returns a dict with non-empty "text".
    """
    if not _API_KEY:
        logger.warning("LLM_API_KEY not set; skipping reconciliation.")
        return _best_engine_fallback(results)

    try:
        image_b64 = base64.standard_b64encode(image_bytes).decode()
        user_text = _build_user_text(results)

        if _PROVIDER == "anthropic":
            raw = await _call_anthropic(user_text, image_b64)
        elif _PROVIDER in ("openai", "openrouter"):
            raw = await _call_openai_compatible(user_text, image_b64)
        elif _PROVIDER == "groq":
            raw = await _call_groq(user_text, image_b64)
        else:
            logger.error("Unknown LLM_PROVIDER: %s", _PROVIDER)
            return _best_engine_fallback(results)

        return _parse_llm_response(raw)
    except Exception as exc:
        logger.error("LLM reconciliation failed: %s", exc)
        return _best_engine_fallback(results)


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

async def _call_anthropic(user_text: str, image_b64: str) -> str:
    """
    Why: Anthropic's Messages API has a different schema from OpenAI-compatible APIs.
    What: POSTs to https://api.anthropic.com/v1/messages with the image as a base64
          vision block and returns the first content block text.
    Test: Mock httpx.AsyncClient.post to return {"content": [{"text": '{"text":"hi","structured":{}}'}]};
          assert the return value equals '{"text":"hi","structured":{}}'.
    """
    payload = {
        "model": _MODEL,
        "max_tokens": 2048,
        "system": _SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": user_text},
                ],
            }
        ],
    }
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": _API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        return data["content"][0]["text"]


async def _call_openai_compatible(user_text: str, image_b64: str) -> str:
    """
    Why: OpenAI and OpenRouter share the same /chat/completions schema, so one
         function handles both to avoid duplication.
    What: POSTs to the appropriate base URL with an image_url vision block and
          returns the first choice message content string.
    Test: Mock httpx.AsyncClient.post to return an OpenAI-format completion dict;
          assert return value is the expected content string.
    """
    base_url = (
        "https://openrouter.ai/api/v1"
        if _PROVIDER == "openrouter"
        else "https://api.openai.com/v1"
    )
    payload = {
        "model": _MODEL,
        "max_tokens": 2048,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                    {"type": "text", "text": user_text},
                ],
            },
        ],
    }
    headers = {
        "Authorization": f"Bearer {_API_KEY}",
        "Content-Type": "application/json",
    }
    if _PROVIDER == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/polycr"
        headers["X-Title"] = "polycr"

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


async def _call_groq(user_text: str, image_b64: str) -> str:
    """
    Why: Groq uses an OpenAI-compatible API but requires its own base URL and does
         not support all models; isolated here so the base URL is never confused.
    What: POSTs to https://api.groq.com/openai/v1/chat/completions and returns the
          first choice message content.
    Test: Mock httpx.AsyncClient.post to return a Groq-format completion response;
          assert the parsed text matches the expected content.
    """
    payload = {
        "model": _MODEL,
        "max_tokens": 2048,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                    {"type": "text", "text": user_text},
                ],
            },
        ],
    }
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_user_text(results: list[EngineResult]) -> str:
    """
    Why: A clearly labelled listing of each engine's output helps the LLM cross-
         reference discrepancies and select the most likely correct tokens.
    What: Formats each EngineResult into a labelled block; marks failed engines.
    Test: Pass two EngineResults (one with text, one with error); assert both engine
          names appear in the output and the errored engine is marked as failed.
    """
    lines = ["OCR Engine Outputs:", ""]
    for r in results:
        if r.error:
            lines.append(f"[{r.engine.upper()}] (FAILED: {r.error})")
        else:
            lines.append(
                f"[{r.engine.upper()}] (confidence: {r.confidence:.1f}%)\n{r.text}"
            )
        lines.append("")
    lines.append(
        "Please reconcile the above into a single accurate transcription and extract "
        "all structured fields. Return ONLY valid JSON as instructed."
    )
    return "\n".join(lines)


def _parse_llm_response(raw: str) -> dict[str, Any]:
    """
    Why: LLMs occasionally wrap JSON in markdown fences despite instructions not to;
         stripping them ensures reliable json.loads parsing.
    What: Removes leading/trailing ```json ... ``` or ``` ... ``` fences, then parses
          the cleaned string with json.loads.  Returns fallback dict on any error.
    Test: Pass '```json\\n{"text":"hi","structured":{}}\\n```'; assert return equals
          {"text": "hi", "structured": {}}.
          Pass plain invalid JSON; assert return equals _FALLBACK_RESULT.
    """
    cleaned = raw.strip()
    # Strip ```json ... ``` or ``` ... ``` fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict) and "text" in parsed:
            return parsed
        logger.warning("LLM returned unexpected JSON shape: %s", list(parsed.keys()))
        return _FALLBACK_RESULT
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse LLM JSON response: %s | raw: %.200s", exc, raw)
        return _FALLBACK_RESULT


def _best_engine_fallback(results: list[EngineResult]) -> dict[str, Any]:
    """
    Why: When the LLM is unavailable or fails, we still want to return something
         useful rather than an empty string.
    What: Selects the EngineResult with the highest confidence that has no error,
          returns its text under the "text" key with an empty "structured" dict.
    Test: Pass three EngineResults with confidences 40, 80, 60; assert the return
          {"text": ...} matches the text of the 80-confidence result.
    """
    successful = [r for r in results if not r.error]
    if not successful:
        return _FALLBACK_RESULT
    best = max(successful, key=lambda r: r.confidence)
    return {"text": best.text, "structured": {}}
