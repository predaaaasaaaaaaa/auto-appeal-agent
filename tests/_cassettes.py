"""
Lightweight VCR-style record/replay for Anthropic API calls in tests.

Plain-language summary: each test that hits Claude uses a `cassette` —
a JSON file under `tests/cassettes/` that holds the recorded responses
for that test's API requests. On normal runs, the test reads from the
cassette and never touches the real API (deterministic, fast, free).
Set `RECORD_CASSETTES=1` (or just delete the cassette file) to refresh
the recordings against the live API.

How a cassette key is built: a stable hash of the request payload
(model, system prompt, messages, tools, tool_choice, thinking flag).
If a prompt changes, the key changes, the cassette misses, and the
test asks you to re-record. That's the right behaviour: prompt changes
should be deliberate, recorded, and committed.

Usage in tests:

    def test_something(cassette):
        # Inside this test, get_client() is patched to return the
        # cassette, so any agent call replays from disk.
        result = analyze_denial("case_01_ozempic_bmi34", path)
        assert result.case_id == "case_01_ozempic_bmi34"
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

CASSETTES_DIR = Path(__file__).resolve().parent / "cassettes"

# Set RECORD_CASSETTES=1 to force re-recording (overwrites existing cassettes).
RECORD_MODE = os.getenv("RECORD_CASSETTES") == "1"


def _key(kwargs: dict[str, Any]) -> str:
    """Stable hash of the request payload, used as cassette lookup key."""
    payload = json.dumps(
        {
            "model": kwargs.get("model"),
            "system": kwargs.get("system"),
            "messages": kwargs.get("messages"),
            "tools": kwargs.get("tools"),
            "tool_choice": kwargs.get("tool_choice"),
            "thinking": kwargs.get("thinking"),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class _CassetteMessages:
    """Mimics `client.messages` — only `create()` is implemented."""

    def __init__(self, cassette: "Cassette") -> None:
        self._c = cassette

    def create(self, **kwargs: Any):  # type: ignore[no-untyped-def]
        from anthropic.types import Message

        key = _key(kwargs)

        if self._c.record:
            assert self._c.real is not None, "record mode requires a real client"
            response = self._c.real.messages.create(**kwargs)
            self._c.data[key] = response.model_dump(mode="json")
            return response

        if key not in self._c.data:
            raise KeyError(
                f"No cassette entry in {self._c.path.name} for request key {key}.\n"
                "Re-record with: RECORD_CASSETTES=1 pytest <test_path>"
            )
        return Message.model_validate(self._c.data[key])


class Cassette:
    """Drop-in replacement for an Anthropic client that records or replays."""

    def __init__(self, name: str) -> None:
        self.path = CASSETTES_DIR / f"{name}.json"
        self.data: dict[str, Any] = {}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

        # Record when explicitly asked, OR when no cassette exists yet.
        self.record: bool = RECORD_MODE or not self.path.exists()
        self.real: Optional[Any] = None
        if self.record:
            from anthropic import Anthropic

            self.real = Anthropic()

        self.messages = _CassetteMessages(self)

    def save(self) -> None:
        if self.record:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.data, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )


def patch_client(monkeypatch, name: str) -> Cassette:
    """Patch `anthropic_client.get_client` to return a fresh Cassette."""
    cassette = Cassette(name)

    from auto_appeal_agent import anthropic_client

    # The real get_client uses lru_cache; bust it before patching so the
    # next call goes through our patched version.
    anthropic_client.get_client.cache_clear()
    monkeypatch.setattr(anthropic_client, "get_client", lambda: cassette)
    return cassette
