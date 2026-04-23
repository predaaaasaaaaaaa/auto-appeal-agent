"""
Tests for anthropic_client.

Non-integration tests (no API call, always run) verify tool-schema
conversion and input validation. The integration test makes a real
(tiny, ~cents) API call to confirm the round-trip works; it only runs
when you explicitly pass `-m integration`.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict, Field

from auto_appeal_agent.anthropic_client import (
    call_claude_structured,
    schema_to_tool,
)


class _DemoGreeting(BaseModel):
    """Tiny schema used only by these tests."""

    model_config = ConfigDict(extra="forbid")
    words: list[str] = Field(..., description="words in the greeting")


def test_schema_to_tool_has_correct_shape():
    tool = schema_to_tool(_DemoGreeting)
    assert tool["name"] == "emit_structured_output"
    assert "_DemoGreeting" in tool["description"]
    # The input_schema must be the Pydantic JSON schema.
    assert "properties" in tool["input_schema"]
    assert tool["input_schema"]["properties"]["words"]["type"] == "array"


def test_schema_to_tool_custom_name():
    tool = schema_to_tool(_DemoGreeting, tool_name="emit_greeting")
    assert tool["name"] == "emit_greeting"


def test_structured_output_roundtrip(cassette):
    """Cassette-backed: first run records, subsequent runs replay for free.
    Verifies that tool_use round-tripping works end-to-end against the real
    API shape."""
    greeting, raw = call_claude_structured(
        output_model=_DemoGreeting,
        system=(
            "You are being tested. Emit a Greeting object whose `words` "
            "list contains at least two strings. Use any friendly words."
        ),
        messages=[{"role": "user", "content": "Greet me."}],
        max_tokens=200,
    )
    assert isinstance(greeting, _DemoGreeting)
    assert len(greeting.words) >= 1
    assert all(isinstance(w, str) for w in greeting.words)
    assert raw.usage.input_tokens > 0
    assert raw.usage.output_tokens > 0
