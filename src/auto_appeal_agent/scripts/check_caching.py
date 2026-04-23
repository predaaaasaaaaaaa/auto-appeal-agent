"""
Live check that prompt caching is actually firing on Anthropic's side.

Calls DenialAnalyzer twice against case_01 within the cache TTL window,
prints `usage.cache_creation_input_tokens` and `cache_read_input_tokens`
for both calls. The second call should show cache_read > 0 (the system
prompt was cached on the first call and reused on the second).

Run:
    .venv/bin/python -m auto_appeal_agent.scripts.check_caching

Cost: ~$0.30 (2 real Claude calls).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from auto_appeal_agent.anthropic_client import (
    call_claude_structured,
    cached_system,
)
from auto_appeal_agent.pdf_utils import render_pdf_to_image_blocks
from auto_appeal_agent.schemas import DenialAnalysis

REPO_ROOT = Path(__file__).resolve().parents[3]
CASE_DIR = REPO_ROOT / "fixtures" / "case_01_ozempic_bmi34"

_SYSTEM_PROMPT = (
    "You are a healthcare prior-authorization specialist. Read the denial "
    "letter and emit a structured DenialAnalysis. Every quote must be "
    "verbatim from the letter; quote_id format 'denial_qN'; source_type "
    "'denial_letter'. case_id must match the user's case_id."
)


def _print_usage(label: str, raw: Any) -> None:
    u = raw.usage
    cache_create = getattr(u, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
    print(
        f"{label}: input={u.input_tokens}  output={u.output_tokens}  "
        f"cache_create={cache_create}  cache_read={cache_read}"
    )


def _call() -> Any:
    image_blocks = render_pdf_to_image_blocks(CASE_DIR / "denial_letter.pdf")
    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": "Analyze the denial letter for case_id='case_01_ozempic_bmi34'.",
        },
        *image_blocks,
    ]
    _, raw = call_claude_structured(
        output_model=DenialAnalysis,
        system=cached_system(_SYSTEM_PROMPT),
        messages=[{"role": "user", "content": user_content}],
        max_tokens=2048,
    )
    return raw


def main() -> None:
    print("--- First call (writes cache) ---")
    raw1 = _call()
    _print_usage("call 1", raw1)

    print()
    print("Sleeping 2s, then calling again (should hit cache)...")
    time.sleep(2)

    raw2 = _call()
    _print_usage("call 2", raw2)

    cache_read = getattr(raw2.usage, "cache_read_input_tokens", 0) or 0
    if cache_read > 0:
        print(
            f"\nOK: cache hit on call 2 ({cache_read} tokens "
            f"read from cache, billed at ~10% of normal input cost)."
        )
    else:
        print(
            "\nWARNING: no cache read on call 2. "
            "Possible reasons: system prompt below cache threshold, "
            "cache TTL expired, account/feature flag."
        )


if __name__ == "__main__":
    main()
