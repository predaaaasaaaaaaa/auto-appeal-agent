"""
anthropic_client.py — cached, structured-output Claude client.

Plain-language summary: a thin wrapper around the Anthropic Python SDK
that every agent in this project uses to talk to Claude. It centralizes
three things:

  1. Loading the API key from .env at import time (python-dotenv).
  2. Running Claude and parsing the response through a Pydantic model
     (via the tool-use pattern), so each agent gets back a typed object
     or a clear ValidationError — never free-form text it then has to
     parse itself.
  3. Accepting either a plain-string `system` prompt or a list of system
     content blocks. The list form lets callers mark sections with
     `cache_control` for prompt caching — up to four breakpoints per
     request — so static context (instructions, tool schemas, the whole
     patient chart) gets billed once and reused at ~10% cost.

Design principle: this module is the ONLY place that talks to the
Anthropic SDK. Agents import from here. That way, reliability
improvements (retries, caching, observability) live in one spot.
"""
from __future__ import annotations

import logging
import os
import time
from functools import lru_cache
from typing import Any, Optional, Type, TypeVar, Union

import httpx

from anthropic import Anthropic, APIConnectionError, APIStatusError
from anthropic.types import Message
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

# Load .env at import time so `ANTHROPIC_API_KEY` is available to the SDK.
load_dotenv()

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-7")


# Per-request ceiling. 120s is enough for Opus 4.7 with adaptive
# thinking + large context, but short enough that a truly stuck call
# surfaces quickly instead of hanging for 10 min (the SDK default).
_REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=30.0)


# Transient-infra retry policy. These are Anthropic-side / network
# blips that almost always succeed on a second try; retrying once
# costs almost nothing relative to a failed pipeline run. We
# DELIBERATELY do NOT retry validation errors (deterministic given
# same prompt — wastes money) or 4xx errors (auth/rate-limit/bad
# request — the caller needs to see them).
_TRANSIENT_HTTP_STATUS_CODES = (502, 503, 504, 529)
_TRANSIENT_HTTP_RETRIES = 1
_TRANSIENT_HTTP_BACKOFF_SECONDS = 2.0


@lru_cache(maxsize=1)
def get_client() -> Anthropic:
    """Return a singleton Anthropic client with fail-fast network policy.

    The SDK reads ANTHROPIC_API_KEY from the environment on its own; we
    just check here to raise a friendly error if the key is missing,
    instead of letting the first API call blow up with a cryptic 401.

    We also pin `timeout` and `max_retries=0` so the client:
      - Fails within ~2 minutes rather than the SDK default 10-minute
        read timeout (adaptive thinking can legitimately take 30-60s,
        but 120s is the UX ceiling — past that the UI is unusable).
      - Does NOT transparently retry on 429/529/network errors. Those
        retries multiply spend during incidents. Surface the failure
        to the caller fast; the user or operator can retry manually.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.template to .env "
            "and paste your key there."
        )
    return Anthropic(timeout=_REQUEST_TIMEOUT, max_retries=0)


def cached_system(text: str) -> list[dict[str, Any]]:
    """Wrap a system prompt as a single cached content block.

    Anthropic's prompt caching reuses the same prefix across requests
    within the cache TTL (5 minutes by default). System prompts are
    identical across pipeline runs, so caching them cuts ~90% of their
    token cost on every call after the first within the window.
    """
    return [
        {
            "type": "text",
            "text": text,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def schema_to_tool(
    output_model: Type[T],
    tool_name: str = "emit_structured_output",
) -> dict[str, Any]:
    """Convert a Pydantic model class into an Anthropic tool definition.

    We use the tool-use pattern for structured output: Claude "calls" a
    synthetic tool whose input schema is the Pydantic model's JSON
    schema. Forcing `tool_choice` to this tool guarantees the response
    is an object matching the schema — or the call raises.

    The tool also carries a `cache_control` marker, which (combined with
    the system prompt above it) creates a cacheable prefix big enough to
    cross Anthropic's ~1024-token cache threshold. On repeat calls
    within the cache TTL, the system+tool prefix is billed at ~10% of
    normal input cost.
    """
    return {
        "name": tool_name,
        "description": (
            f"Emit a structured {output_model.__name__} object. Every "
            "field is required; do not invent fields outside the schema. "
            "Quote fields must contain verbatim text copied character-for-"
            "character from the source document — never paraphrased."
        ),
        "input_schema": output_model.model_json_schema(),
        "cache_control": {"type": "ephemeral"},
    }


def _log_call(
    model_name: str,
    response: Message,
    *,
    elapsed_ms: float,
    attempt: int,
    total_attempts: int,
) -> None:
    """Emit one INFO line summarizing a Claude call for live diagnosis.

    Captures stop_reason + usage + elapsed_ms so that a hung or
    over-spending agent can be diagnosed from logs alone. Critical
    when real-API issues only surface in production-like runs.
    """
    u = response.usage
    cache_c = getattr(u, "cache_creation_input_tokens", 0) or 0
    cache_r = getattr(u, "cache_read_input_tokens", 0) or 0
    content_types = [b.type for b in response.content]
    logger.info(
        "claude_call model=%s attempt=%d/%d elapsed_ms=%.0f "
        "stop_reason=%s input_tokens=%d output_tokens=%d "
        "cache_creation=%d cache_read=%d content_types=%s",
        model_name,
        attempt,
        total_attempts,
        elapsed_ms,
        response.stop_reason,
        u.input_tokens,
        u.output_tokens,
        cache_c,
        cache_r,
        content_types,
    )


# Keys Claude has been observed to wrap real payloads inside, instead
# of emitting the payload at the top level. Each is treated as an
# envelope: if the input dict has only this key and its value is a
# dict, peel one level and use the inner dict as the payload.
_ENVELOPE_KEYS = ("parameter", "$PARAMETER_NAME")


def _is_transient_api_error(exc: BaseException) -> bool:
    """Return True if `exc` is a transient Anthropic / network error worth
    a single quick retry.

    Plain-language summary: the model isn't broken, our request isn't
    broken, the upstream API just had a momentary capacity hiccup
    (529 overloaded), routing blip (502/503/504), or our connection
    died mid-flight. One retry after a short backoff almost always
    succeeds and keeps the live UI demo from crashing on a hiccup.

    Explicitly NOT transient: 4xx (caller bug — auth, rate limit,
    bad request, schema mismatch). Those should surface immediately.
    """
    if isinstance(exc, APIConnectionError):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code in _TRANSIENT_HTTP_STATUS_CODES
    return False


def _create_message_with_transient_retry(request: dict[str, Any]) -> Message:
    """Wrap `client.messages.create(**request)` with one retry on transient errors.

    On a transient error (see `_is_transient_api_error`), sleep
    `_TRANSIENT_HTTP_BACKOFF_SECONDS` and try again — at most
    `_TRANSIENT_HTTP_RETRIES` extra attempts. Anything else
    propagates immediately so the caller sees the real failure.
    """
    last_error: Optional[BaseException] = None
    total_attempts = _TRANSIENT_HTTP_RETRIES + 1
    for attempt in range(1, total_attempts + 1):
        try:
            return get_client().messages.create(**request)
        except (APIConnectionError, APIStatusError) as exc:
            if not _is_transient_api_error(exc):
                raise
            last_error = exc
            if attempt >= total_attempts:
                raise
            logger.warning(
                "Anthropic transient error (attempt %d/%d, retrying in %.1fs): %s",
                attempt,
                total_attempts,
                _TRANSIENT_HTTP_BACKOFF_SECONDS,
                exc,
            )
            time.sleep(_TRANSIENT_HTTP_BACKOFF_SECONDS)
    # Unreachable — the loop either returns, raises non-transient,
    # or raises on the final attempt — but mypy doesn't know that.
    assert last_error is not None
    raise last_error


def _normalize_tool_input(raw_input: Any) -> Any:
    """Defensively clean a tool_use input before Pydantic validation.

    Plain-language summary: Claude usually returns the tool input
    exactly matching our Pydantic schema, but occasionally — observed
    at roughly 1-in-6 calls during live re-recording on 2026-04-24 —
    it leaks meta-schema artifacts into the payload. Three known leak
    shapes, all of which crash strict Pydantic validation:

      1. Bare meta-keys: top-level keys prefixed with "$"
         (e.g. "$FUNCTION_NAME") sit alongside the real fields. The
         model is echoing tool-schema description text. Strip them.
      2. "parameter" envelope: the entire real payload is wrapped one
         level deeper under a single "parameter" key — i.e.
         {"parameter": {"case_id": ...}} instead of {"case_id": ...}.
         The inner content is correct; the model just over-wrapped.
      3. "$PARAMETER_NAME" envelope: same as (2) but the wrap key is
         the literal "$PARAMETER_NAME". Looks like a meta-key but
         actually carries the real payload.

    Since none of our schemas use top-level "$"-prefixed fields and
    none has a sole envelope field, peeling these defensively is safe
    and makes the parser tolerant of model flakiness instead of
    brittle to it. Strip-then-unwrap order matters: a dict like
    {"$FUNCTION_NAME": "...", "parameter": {...}} should first lose
    the meta key, then unwrap the envelope.
    """
    if not isinstance(raw_input, dict):
        return raw_input

    def _strip_meta(d: dict[str, Any]) -> dict[str, Any]:
        return {
            k: v
            for k, v in d.items()
            if not (isinstance(k, str) and k.startswith("$"))
        }

    # Check for an envelope BEFORE stripping `$`-keys, because one of
    # the envelope keys ("$PARAMETER_NAME") would itself be stripped
    # and the real payload lost. If the input has only one key and
    # that key is an envelope key with a dict value, peel it.
    if len(raw_input) == 1:
        only_key = next(iter(raw_input))
        only_val = raw_input[only_key]
        if only_key in _ENVELOPE_KEYS and isinstance(only_val, dict):
            return _strip_meta(only_val)

    # Otherwise: just strip meta keys at the top level. If the result
    # then has a single envelope key, peel it.
    cleaned = _strip_meta(raw_input)
    if len(cleaned) == 1:
        only_key = next(iter(cleaned))
        only_val = cleaned[only_key]
        if only_key in _ENVELOPE_KEYS and isinstance(only_val, dict):
            return _strip_meta(only_val)
    return cleaned


def call_claude_structured(
    output_model: Type[T],
    system: Union[str, list[dict[str, Any]]],
    messages: list[dict[str, Any]],
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4096,
    thinking: bool = False,
    thinking_effort: str = "medium",
    max_retries: int = 0,
    retry_sleep_seconds: float = 1.0,
) -> tuple[T, Message]:
    """Call Claude and return a validated Pydantic instance of `output_model`.

    Args:
        output_model: The Pydantic class the response must fit. Strict
            config (`extra="forbid"`) catches hallucinated extra fields.
        system: Either a plain string, or a list of content blocks
            (each block may carry `cache_control` for prompt caching).
        messages: The user/assistant turns.
        model: Model ID (default from ANTHROPIC_MODEL env var).
        max_tokens: Hard cap on generated tokens for this single request.
        thinking: If True, enables adaptive thinking. Adds tokens but
            helps on complex reasoning (ChartMiner, LetterWriter).
        thinking_effort: Caps adaptive-thinking spend. Valid values
            (per Anthropic SDK): "low", "medium", "high", "xhigh",
            "max". Ignored when thinking=False. Without a cap, Opus
            4.7's adaptive thinking can exhaust the entire max_tokens
            budget reasoning *before* it emits the tool call, causing
            the response to stop without a tool_use block.
        max_retries: Number of additional attempts if the first call
            raises ValidationError (bad shape) or RuntimeError (no
            tool_use block returned). Default is 0 — fail fast. Each
            retry is a full-priced API call, and the common failure
            modes (adaptive thinking eating all tokens, model skipping
            the tool) are deterministic given the same prompt, so
            retries usually just burn money. Opt in by passing
            `max_retries=N` if a specific agent genuinely benefits.
        retry_sleep_seconds: Seconds to wait before each retry.

    Returns:
        (parsed, raw) where `parsed` is the validated Pydantic instance
        and `raw` is the full anthropic.types.Message so callers can
        inspect `raw.usage` (input/output/cache tokens).

    Raises:
        RuntimeError if every attempt returned no tool_use block.
        pydantic.ValidationError if every attempt failed schema validation.
    """
    tool = schema_to_tool(output_model)
    # tool_choice rules (per Anthropic API):
    #   - "tool"/"any": force tool use; NOT compatible with `thinking`.
    #   - "auto": Claude chooses; compatible with `thinking`.
    # When the caller wants adaptive thinking, we must use "auto" and
    # rely on a strong system prompt to still elicit the tool call. If
    # Claude skips the tool, we raise RuntimeError below.
    tool_choice: dict[str, Any] = (
        {"type": "auto"} if thinking else {"type": "any"}
    )
    request: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "tools": [tool],
        "tool_choice": tool_choice,
    }
    if thinking:
        request["thinking"] = {"type": "adaptive"}
        # Cap the adaptive-thinking budget so the model can't burn the
        # entire max_tokens window on reasoning and then fail to emit
        # the tool call.
        request["output_config"] = {"effort": thinking_effort}

    last_error: Optional[Exception] = None
    total_attempts = max_retries + 1
    for attempt in range(1, total_attempts + 1):
        call_started = time.monotonic()
        try:
            # Single retry on transient Anthropic/network errors (529
            # overloaded, 502/503/504, dropped connection). Validation
            # retries (max_retries) sit OUTSIDE this — different
            # failure mode, different policy.
            response = _create_message_with_transient_retry(request)
            _log_call(
                output_model.__name__,
                response,
                elapsed_ms=(time.monotonic() - call_started) * 1000,
                attempt=attempt,
                total_attempts=total_attempts,
            )
            for block in response.content:
                if block.type == "tool_use":
                    raw_input = _normalize_tool_input(block.input)
                    parsed = output_model.model_validate(raw_input)
                    return parsed, response
            raise RuntimeError(
                "Claude returned no tool_use block. "
                f"stop_reason={response.stop_reason} "
                f"content_types={[b.type for b in response.content]}"
            )
        except (ValidationError, RuntimeError) as e:
            last_error = e
            logger.warning(
                "Claude call attempt %d/%d failed: %s: %s",
                attempt,
                total_attempts,
                type(e).__name__,
                e,
            )
            if attempt < total_attempts:
                time.sleep(retry_sleep_seconds)

    assert last_error is not None
    raise last_error
