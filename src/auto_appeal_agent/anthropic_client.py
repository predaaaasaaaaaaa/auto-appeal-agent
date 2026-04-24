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

from anthropic import Anthropic
from anthropic.types import Message
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

# Load .env at import time so `ANTHROPIC_API_KEY` is available to the SDK.
load_dotenv()

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-7")


@lru_cache(maxsize=1)
def get_client() -> Anthropic:
    """Return a singleton Anthropic client.

    The SDK reads ANTHROPIC_API_KEY from the environment on its own; we
    just check here to raise a friendly error if the key is missing,
    instead of letting the first API call blow up with a cryptic 401.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.template to .env "
            "and paste your key there."
        )
    return Anthropic()


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


def call_claude_structured(
    output_model: Type[T],
    system: Union[str, list[dict[str, Any]]],
    messages: list[dict[str, Any]],
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4096,
    thinking: bool = False,
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

    last_error: Optional[Exception] = None
    total_attempts = max_retries + 1
    for attempt in range(1, total_attempts + 1):
        try:
            response = get_client().messages.create(**request)
            for block in response.content:
                if block.type == "tool_use":
                    # Claude occasionally leaks tool-schema metadata fields
                    # ("$FUNCTION_NAME", "$PARAMETER_NAME", etc.) into the
                    # tool input payload. These aren't part of any user-
                    # defined schema and break strict Pydantic models, so
                    # strip them defensively before validation.
                    raw_input = block.input
                    if isinstance(raw_input, dict):
                        raw_input = {
                            k: v
                            for k, v in raw_input.items()
                            if not (isinstance(k, str) and k.startswith("$"))
                        }
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
