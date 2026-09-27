"""Thin wrapper around any OpenAI-compatible LLM (Groq, Ollama, Cerebras...).

Provider is set in .env (LLM_BASE_URL, LLM_API_KEY, LLM_MODEL), so switching
from Groq to Ollama is a config change, not a code change.

Failures are counted in STATS and printed, never swallowed silently: an eval run
that quietly falls back on every call would look like a real result.
"""
import json
import re
import sys
import time

from openai import APIStatusError, OpenAI

from app.core.config import get_settings

settings = get_settings()
client = OpenAI(api_key=settings.LLM_API_KEY or "none", base_url=settings.LLM_BASE_URL)

STATS = {"calls": 0, "ok": 0, "failed": 0, "last_error": None}
NON_RETRYABLE = {400, 401, 403, 404}   # bad request / auth / model not found: retrying won't help

_last_call = 0.0   # time of the previous request, for rate limiting


def _throttle() -> None:
    """Wait so calls are at least LLM_MIN_INTERVAL seconds apart (free-tier limits)."""
    global _last_call
    wait = settings.LLM_MIN_INTERVAL - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()


def _extra_args(max_tokens: int, model: str) -> dict:
    """Model-specific settings. Reasoning models (gpt-oss) think before answering;
    without room for that, the visible answer comes back empty."""
    model = model.lower()
    if "gpt-oss" in model:
        return {"max_tokens": max(max_tokens, 2000), "reasoning_effort": "low"}
    return {"max_tokens": max_tokens}


def chat_json(prompt: str, max_tokens: int = 800, retries: int = 3, model: str | None = None) -> dict:
    """Send a prompt, return the parsed JSON object. Raises after `retries` failures.
    `model` overrides LLM_MODEL (used by the eval judge, so it isn't the answer model)."""
    model = model or settings.LLM_MODEL
    if settings.LLM_NO_THINK and "qwen3" in model.lower():
        prompt += "\n/no_think"          # Qwen3 only: skip slow "thinking"

    STATS["calls"] += 1
    last_err = None
    for attempt in range(retries):
        _throttle()
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,           # same input -> same output, so evals are repeatable
                **_extra_args(max_tokens, model),
            )
            text = r.choices[0].message.content or ""
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)   # strip reasoning, if any
            if not text.strip():
                raise ValueError("empty response (model may have used all tokens on reasoning)")
            out = json.loads(text)
            STATS["ok"] += 1
            return out
        except Exception as e:
            last_err = e
            msg = f"{type(e).__name__}: {str(e)[:200]}"
            print(f"    [llm] attempt {attempt + 1}/{retries} failed: {msg}", file=sys.stderr, flush=True)
            if isinstance(e, APIStatusError) and e.status_code in NON_RETRYABLE:
                break                        # e.g. 404 model not found: stop now, don't wait 60s
            time.sleep(10 * (attempt + 1))   # back off: 10s, 20s (rate limits, bad JSON)
    STATS["failed"] += 1
    STATS["last_error"] = f"{type(last_err).__name__}: {str(last_err)[:200]}"
    raise RuntimeError(f"LLM call failed: {STATS['last_error']}")
