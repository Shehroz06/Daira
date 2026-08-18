"""LLM provider layer for Diara.

Exposes a provider-agnostic API:

    generate(...)            -> (text, provider)
    stream_generate(...)     -> (chunk_iterator, provider)
    generate_structured(...) -> (dict_or_None, provider)

Providers:
    - Gemini (preferred when configured, reachable, and under its own
      self-imposed rate limit)
    - Ollama (local fallback; always kept fully functional)

All Gemini failure modes (no key, network, timeout, rate limit, HTTP error,
invalid response, malformed JSON) degrade gracefully to Ollama. Callers only
see LLMError when *no* provider can serve the request.

Gemini calls are also proactively throttled client-side (GEMINI_MAX_RPM) so
Diara stops calling Gemini *before* Google's own rate limit would reject the
request — a skipped call and an instant Ollama fallback beats a wasted
round-trip that ends in a 429.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import deque
from pathlib import Path
from typing import Iterator, Optional

import httpx
from dotenv import load_dotenv

# Load .env explicitly by path so this works regardless of the caller's cwd
# (uvicorn from the project root, or a script run from scripts/).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger("diara.llm")

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "").strip() or "gemini-2.0-flash"
GEMINI_ENABLED = os.getenv("GEMINI_ENABLED", "true").strip().lower() in ("1", "true", "yes")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# auto | gemini | ollama
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "auto").strip().lower()

GEMINI_TIMEOUT = float(os.getenv("GEMINI_TIMEOUT", "30"))
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "120"))

# Client-side cap on Gemini calls per rolling 60s window. Free-tier Gemini
# quotas are commonly in the ~15 RPM range; default conservatively and let
# it be tuned per-key via env var.
GEMINI_MAX_RPM = int(os.getenv("GEMINI_MAX_RPM", "15"))

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Timestamps (epoch seconds) of recent Gemini calls, oldest first.
_gemini_call_times: deque[float] = deque()


class LLMError(Exception):
    """Raised only when no provider could serve the request."""


def gemini_available() -> bool:
    """Whether Gemini is configured for use at all (not a per-call check)."""
    return bool(GEMINI_API_KEY) and GEMINI_ENABLED and LLM_PROVIDER in ("auto", "gemini")


def _gemini_under_rate_limit() -> bool:
    """Whether calling Gemini right now would stay within GEMINI_MAX_RPM."""
    now = time.time()
    while _gemini_call_times and now - _gemini_call_times[0] > 60:
        _gemini_call_times.popleft()
    return len(_gemini_call_times) < GEMINI_MAX_RPM


def _record_gemini_call() -> None:
    _gemini_call_times.append(time.time())


def _gemini_ready() -> bool:
    """gemini_available() plus the proactive rate-limit check — the actual
    per-call gate used before attempting a Gemini request."""
    if not gemini_available():
        return False
    if not _gemini_under_rate_limit():
        logger.info("Gemini call skipped — at self-imposed %d RPM cap, falling back to Ollama",
                     GEMINI_MAX_RPM)
        return False
    return True


def _ollama_allowed() -> bool:
    return LLM_PROVIDER in ("auto", "ollama")


# --------------------------------------------------------------------------
# Gemini provider
# --------------------------------------------------------------------------

def _gemini_payload(prompt: str, system: Optional[str], json_mode: bool) -> dict:
    payload: dict = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    if json_mode:
        payload["generationConfig"] = {"responseMimeType": "application/json"}
    return payload


def _gemini_generate(prompt: str, system: Optional[str] = None, json_mode: bool = False) -> str:
    _record_gemini_call()
    url = f"{_GEMINI_BASE}/{GEMINI_MODEL}:generateContent"
    with httpx.Client(timeout=GEMINI_TIMEOUT) as client:
        resp = client.post(
            url,
            params={"key": GEMINI_API_KEY},
            json=_gemini_payload(prompt, system, json_mode),
        )
        resp.raise_for_status()
        data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Gemini returned unexpected response shape: {exc}") from exc


def _gemini_stream(prompt: str, system: Optional[str] = None) -> Iterator[str]:
    _record_gemini_call()
    url = f"{_GEMINI_BASE}/{GEMINI_MODEL}:streamGenerateContent"
    with httpx.Client(timeout=GEMINI_TIMEOUT) as client:
        with client.stream(
            "POST",
            url,
            params={"key": GEMINI_API_KEY, "alt": "sse"},
            json=_gemini_payload(prompt, system, False),
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                chunk = line[len("data:"):].strip()
                if not chunk or chunk == "[DONE]":
                    continue
                try:
                    data = json.loads(chunk)
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                    continue
                if text:
                    yield text


# --------------------------------------------------------------------------
# Ollama provider
# --------------------------------------------------------------------------

def _ollama_generate(prompt: str, system: Optional[str] = None, json_mode: bool = False) -> str:
    payload: dict = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
    if system:
        payload["system"] = system
    if json_mode:
        payload["format"] = "json"
    with httpx.Client(timeout=OLLAMA_TIMEOUT) as client:
        resp = client.post(f"{OLLAMA_URL}/api/generate", json=payload)
        resp.raise_for_status()
        return resp.json().get("response", "")


def _ollama_stream(prompt: str, system: Optional[str] = None) -> Iterator[str]:
    payload: dict = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": True}
    if system:
        payload["system"] = system
    with httpx.Client(timeout=OLLAMA_TIMEOUT) as client:
        with client.stream("POST", f"{OLLAMA_URL}/api/generate", json=payload) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                text = data.get("response", "")
                if text:
                    yield text
                if data.get("done"):
                    break


def ollama_embed(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts with the local Ollama embedding model."""
    with httpx.Client(timeout=OLLAMA_TIMEOUT) as client:
        resp = client.post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": OLLAMA_EMBED_MODEL, "input": texts},
        )
        resp.raise_for_status()
        embeddings = resp.json().get("embeddings")
    if not embeddings or len(embeddings) != len(texts):
        raise LLMError("Ollama embed returned unexpected number of embeddings")
    return embeddings


# --------------------------------------------------------------------------
# Public provider-agnostic API
# --------------------------------------------------------------------------

def generate(prompt: str, system: Optional[str] = None) -> tuple[str, str]:
    """Generate a full completion. Returns (text, provider_name)."""
    if _gemini_ready():
        try:
            return _gemini_generate(prompt, system), "gemini"
        except Exception as exc:  # any Gemini failure -> fallback
            logger.warning("Gemini generate failed, falling back to Ollama: %s", exc)
    if _ollama_allowed():
        try:
            return _ollama_generate(prompt, system), "ollama"
        except Exception as exc:
            raise LLMError(f"Ollama generate failed: {exc}") from exc
    raise LLMError("No LLM provider available")


def stream_generate(prompt: str, system: Optional[str] = None) -> tuple[Iterator[str], str]:
    """Stream a completion. Returns (chunk_iterator, provider_name).

    If Gemini fails before producing any output, transparently restarts on
    Ollama. If it fails after partial output, the stream ends gracefully
    (the frontend keeps what was received).
    """
    if _gemini_ready():
        try:
            gen = _gemini_stream(prompt, system)
            first = next(gen, None)  # force connection + first chunk
            if first is not None:
                def _chain() -> Iterator[str]:
                    yield first
                    try:
                        yield from gen
                    except Exception as exc:
                        logger.warning("Gemini stream broke mid-response: %s", exc)
                return _chain(), "gemini"
            logger.warning("Gemini stream produced no output, falling back to Ollama")
        except Exception as exc:
            logger.warning("Gemini stream failed, falling back to Ollama: %s", exc)
    if _ollama_allowed():
        try:
            gen = _ollama_stream(prompt, system)
            first = next(gen, None)

            def _chain_ollama() -> Iterator[str]:
                if first is not None:
                    yield first
                yield from gen

            return _chain_ollama(), "ollama"
        except Exception as exc:
            raise LLMError(f"Ollama stream failed: {exc}") from exc
    raise LLMError("No LLM provider available")


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _safe_parse_json(text: str) -> Optional[dict]:
    """Best-effort JSON object extraction from LLM output."""
    if not text:
        return None
    text = text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK_RE.search(text)
    if match:
        try:
            obj = json.loads(match.group(0))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            pass
    return None


def generate_structured(prompt: str, system: Optional[str] = None) -> tuple[Optional[dict], str]:
    """Generate a JSON object. Returns (dict_or_None, provider_name).

    Never raises for malformed output — returns (None, "none") in the worst
    case so callers can fall back to the raw natural-language query.
    """
    if _gemini_ready():
        try:
            raw = _gemini_generate(prompt, system, json_mode=True)
            parsed = _safe_parse_json(raw)
            if parsed is not None:
                return parsed, "gemini"
            logger.warning("Gemini returned malformed JSON, trying Ollama")
        except Exception as exc:
            logger.warning("Gemini structured call failed, trying Ollama: %s", exc)
    if _ollama_allowed():
        try:
            raw = _ollama_generate(prompt, system, json_mode=True)
            return _safe_parse_json(raw), "ollama"
        except Exception as exc:
            logger.warning("Ollama structured call failed: %s", exc)
    return None, "none"
