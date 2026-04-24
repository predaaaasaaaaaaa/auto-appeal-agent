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
    _normalize_tool_input,
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


def test_normalize_tool_input_passes_clean_payload_through():
    """Ordinary tool inputs should round-trip unchanged."""
    payload = {"case_id": "x", "items": [1, 2]}
    assert _normalize_tool_input(payload) == payload


def test_normalize_tool_input_strips_dollar_prefixed_meta_keys():
    """`$FUNCTION_NAME`-style schema metadata mixed with real fields
    must be stripped (real fields stay, meta keys go)."""
    payload = {
        "$FUNCTION_NAME": "emit_structured_output",
        "case_id": "x",
        "items": [1],
    }
    assert _normalize_tool_input(payload) == {"case_id": "x", "items": [1]}


def test_normalize_tool_input_unwraps_parameter_envelope():
    """Live-API regression (2026-04-24): Claude sometimes wraps the
    real payload one level deeper under a sole "parameter" key. The
    parser must peel that envelope so the inner payload (which IS
    structurally correct) reaches Pydantic."""
    payload = {"parameter": {"case_id": "case_03_pt_extension", "items": [1]}}
    assert _normalize_tool_input(payload) == {
        "case_id": "case_03_pt_extension",
        "items": [1],
    }


def test_normalize_tool_input_unwraps_dollar_parameter_name_envelope():
    """Live-API regression (2026-04-24): Claude sometimes wraps the
    entire real payload under "$PARAMETER_NAME" — the literal meta-
    schema key. Naively stripping all $-keys would drop the real
    data, so the envelope must be unwrapped first."""
    payload = {
        "$PARAMETER_NAME": {
            "case_id": "case_01_ozempic_bmi34",
            "citations": [{"id": "g1"}],
        }
    }
    assert _normalize_tool_input(payload) == {
        "case_id": "case_01_ozempic_bmi34",
        "citations": [{"id": "g1"}],
    }


def test_normalize_tool_input_unwraps_envelope_then_strips_meta():
    """Combined leak: envelope wrap + $-prefixed meta inside it."""
    payload = {
        "parameter": {
            "$FUNCTION_NAME": "emit_structured_output",
            "case_id": "x",
            "items": [1],
        }
    }
    assert _normalize_tool_input(payload) == {"case_id": "x", "items": [1]}


def test_normalize_tool_input_does_not_unwrap_when_parameter_is_legit_field():
    """If a schema legitimately had a `parameter` field alongside others,
    the dict would have >1 keys and we must NOT unwrap. (Defensive: none
    of our schemas hit this today, but the rule needs to hold.)"""
    payload = {"parameter": {"x": 1}, "other": 2}
    assert _normalize_tool_input(payload) == {"parameter": {"x": 1}, "other": 2}


def test_normalize_tool_input_does_not_unwrap_when_parameter_is_not_dict():
    """`parameter` as a primitive value is just a field, not an envelope."""
    payload = {"parameter": "scalar-value"}
    assert _normalize_tool_input(payload) == {"parameter": "scalar-value"}


def test_normalize_tool_input_passes_non_dict_through():
    """Non-dict inputs (defensive — shouldn't happen) are returned as-is."""
    assert _normalize_tool_input("string") == "string"
    assert _normalize_tool_input(None) is None
    assert _normalize_tool_input([1, 2]) == [1, 2]


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
