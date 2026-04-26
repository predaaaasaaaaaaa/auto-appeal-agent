"""
FastAPI backend for the auto-appeal-agent UI.

Endpoints:
  GET  /api/health                          — liveness
  GET  /api/cases                           — list fixture cases
  GET  /api/case/{case_id}/source/{kind}    — raw text of a source doc
  GET  /api/run/{case_id}                   — run pipeline, stream SSE
  POST /api/export_pdf                      — render an AppealDraft to PDF

The SSE run endpoint streams events like
    {"stage": "denial_analyzer", "status": "running"}
    {"stage": "denial_analyzer", "status": "done", "source_quotes": 3}
    ...
    {"stage": "done", "result": <full VerifiedAppeal JSON>}

Run locally:
    make api   # or
    .venv/bin/uvicorn auto_appeal_agent.api.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Optional

# Configure root logging so auto_appeal_agent.* loggers surface in
# the uvicorn terminal. LOG_LEVEL env var (from .env) wins if set;
# otherwise INFO is sensible for live diagnosis.
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

# Module-level logger. Used by the SSE handler's PipelineCancelled
# catch (line ~180) to record client-disconnect cancellations.
# Without this, the catch path raises NameError: name 'logger' is
# not defined and the SSE generator crashes mid-flight — silent
# because by then the client connection is already closing.
logger = logging.getLogger(__name__)

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sse_starlette.sse import EventSourceResponse

from auto_appeal_agent.orchestrator import PipelineCancelled, run_pipeline
from auto_appeal_agent.pdf_export import render_appeal_pdf
from auto_appeal_agent.pdf_utils import extract_text
from auto_appeal_agent.schemas import AppealDraft, PipelineInput

# --------------------------------------------------------------------------
# API authentication
# --------------------------------------------------------------------------
# Single shared key auth — set APPEAL_API_KEY in .env to enable. When set,
# every cost/data endpoint requires the same key in the X-API-Key header
# (or `api_key` query param for EventSource which can't send headers).
# When NOT set, the API logs a startup warning and runs open. That keeps
# the dev / hackathon demo flow zero-config but lets production deploys
# flip a single env var to lock the API down.
#
# This is intentionally minimal: one shared secret, no user accounts,
# no token expiry. Real production should layer on session/OAuth/SSO,
# but a shared pre-shared key meaningfully closes the immediate attack
# (anyone-on-the-network burns $1/call by hitting /api/run) and is
# rotation-friendly via a deploy-time env update.
APPEAL_API_KEY: Optional[str] = os.getenv("APPEAL_API_KEY") or None
if APPEAL_API_KEY is not None and not APPEAL_API_KEY.strip():
    APPEAL_API_KEY = None

if APPEAL_API_KEY is None:
    logger.warning(
        "APPEAL_API_KEY is not set — API endpoints are OPEN. "
        "Set APPEAL_API_KEY in .env to require X-API-Key header. "
        "Required for any non-loopback deployment."
    )
else:
    logger.info("APPEAL_API_KEY is set — X-API-Key header required on cost / data endpoints")


async def require_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> None:
    """FastAPI dependency: require APPEAL_API_KEY when configured.

    Accepts the key via:
      - `X-API-Key` HTTP header (preferred — doesn't leak via URL)
      - `api_key` query param (fallback — needed by browser EventSource
        which has no public API for setting headers)

    Uses `secrets.compare_digest` for constant-time comparison so a
    timing oracle cannot reveal correct key prefixes byte-by-byte.

    No-op when APPEAL_API_KEY is unset — preserves dev / hackathon-demo
    convenience.
    """
    if APPEAL_API_KEY is None:
        return
    presented = x_api_key or request.query_params.get("api_key")
    if not presented or not secrets.compare_digest(presented, APPEAL_API_KEY):
        raise HTTPException(status_code=401, detail="invalid or missing API key")


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_ROOT = REPO_ROOT / "fixtures"
# Pre-resolved (symlinks/.. fully expanded) for cheap is_relative_to
# checks at request time. Eliminates a class of path-traversal bugs
# where a `case_id` like `../../etc/passwd` would have escaped the
# fixtures root if we relied on `is_dir()` alone.
_FIXTURES_ROOT_RESOLVED = FIXTURES_ROOT.resolve()


# --------------------------------------------------------------------------
# Per-case concurrency lock — at most one in-flight pipeline per case_id
# --------------------------------------------------------------------------
# When a user opens two browser tabs and clicks Start on the same case,
# the previous code happily ran two parallel pipelines (each ~$1). This
# guard rejects the second request with 409 Conflict, telling the user
# the case is already being processed. The lock entry is removed in the
# event_stream's finally block so a normal completion frees the case
# for a future re-run.
#
# Implementation: a plain dict + asyncio.Lock for thread-safe
# add/remove. Held only across the entry/exit guard, not for the
# whole pipeline duration — the SSE generator yields control back
# to the event loop after the guard runs.
_active_pipelines: set[str] = set()
_active_pipelines_lock = asyncio.Lock()


# --------------------------------------------------------------------------
# Per-IP rate limit — sliding window over recent calls
# --------------------------------------------------------------------------
# Even with auth + per-case concurrency, a single authenticated client
# could legitimately fire many requests in parallel. The limit is the
# second line of defense: max N calls per IP within a rolling window.
# Configurable via env so a real deployment can tune to its expected
# user behavior.
#
# Two independent buckets:
#   * /api/run         — 5 starts / 60s by default (each ~$1)
#   * /api/export_pdf  — 20 renders / 60s by default (CPU only)
#
# Different cost profiles → different ceilings. Defaults are deliberately
# generous for the demo. Production should tighten based on telemetry.
RATE_LIMIT_WINDOW_SECONDS: float = float(
    os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")
)
RATE_LIMIT_MAX_STARTS: int = int(os.getenv("RATE_LIMIT_MAX_STARTS", "5"))
PDF_RATE_LIMIT_WINDOW_SECONDS: float = float(
    os.getenv("PDF_RATE_LIMIT_WINDOW_SECONDS", "60")
)
PDF_RATE_LIMIT_MAX: int = int(os.getenv("PDF_RATE_LIMIT_MAX", "20"))

# Per-IP timestamps of recent calls. Pruned lazily on each check so
# memory stays bounded by the bucket's max per active IP. One bucket
# per endpoint so /api/run and /api/export_pdf don't share a quota.
_run_rate_log: dict[str, list[float]] = {}
_run_rate_lock = asyncio.Lock()
_pdf_rate_log: dict[str, list[float]] = {}
_pdf_rate_lock = asyncio.Lock()


def _require_client_ip(request: Request) -> str:
    """Return the caller's IP, or raise 400 if it cannot be determined.

    Why not silently default to "unknown": a shared "unknown" bucket
    means anyone whose request.client is None (some proxy / unix-
    socket configs, or test clients) competes for one rate-limit
    quota with every other unknown caller. A single misbehaving
    request can then 429 every legitimate "unknown" client. Raising
    400 here surfaces the deployment misconfiguration instead of
    silently failing into a shared-bucket DoS.
    """
    if request.client is None or not request.client.host:
        raise HTTPException(
            status_code=400,
            detail="cannot determine client IP — check proxy / ASGI config",
        )
    return request.client.host


async def _enforce_rate_limit(
    client_ip: str,
    *,
    log: dict[str, list[float]],
    lock: asyncio.Lock,
    max_in_window: int,
    window_seconds: float,
) -> None:
    """Sliding-window rate limit. Raise 429 if too many recent calls.

    Plain-language summary: we keep a tiny per-IP list of when this
    IP last hit this bucket. Each new request prunes entries older
    than the window, then either rejects (if the list is at the cap)
    or appends. The list is bounded by max_in_window so memory cannot
    grow unbounded.
    """
    now = time.monotonic()
    async with lock:
        timestamps = log.setdefault(client_ip, [])
        cutoff = now - window_seconds
        # Prune in-place so the list never holds entries we'll never check.
        timestamps[:] = [t for t in timestamps if t > cutoff]
        if len(timestamps) >= max_in_window:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"too many requests; max {max_in_window} "
                    f"per {window_seconds:.0f}s — wait and retry"
                ),
            )
        timestamps.append(now)


def _resolve_case_dir(case_id: str) -> Path:
    """Resolve `FIXTURES_ROOT / case_id` and prove it stays inside
    FIXTURES_ROOT.

    Plain-language summary: a malicious request could send
    `case_id = "../../etc/passwd"` and try to read arbitrary files.
    Path joining alone wouldn't catch that — `pathlib` happily
    composes the parents-up traversal. We `resolve()` (which fully
    expands `..` and any symlinks) and then assert the resolved
    path is_relative_to the fixtures root. Anything outside raises
    404 (we deliberately do NOT echo back the attempted path —
    no information leak to attackers).

    Returns the resolved case directory. Caller still needs to
    check `.is_dir()` if they care that the case actually exists.
    """
    candidate = (FIXTURES_ROOT / case_id).resolve()
    try:
        candidate.relative_to(_FIXTURES_ROOT_RESOLVED)
    except ValueError:
        # Outside FIXTURES_ROOT — path traversal attempt.
        raise HTTPException(status_code=404, detail="case not found")
    return candidate

# --------------------------------------------------------------------------
# Max request body size — caps memory before Pydantic ever sees the body
# --------------------------------------------------------------------------
# AppealDraft's per-field max_length bounds (schemas.py) only fire AFTER
# Pydantic deserializes the full request body, so an attacker could send
# a 500MB JSON blob and the server would buffer all of it before
# rejecting with a validation error. This middleware caps the buffer
# before deserialization starts.
#
# Default 2 MiB: a max-shape AppealDraft is ~1 MiB (50 paragraphs × 20KB),
# leaving 2x headroom. Tunable via env if a deployment needs bigger drafts.
MAX_REQUEST_BODY_BYTES: int = int(
    os.getenv("MAX_REQUEST_BODY_BYTES", str(2 * 1024 * 1024))
)


class BodySizeLimitMiddleware:
    """ASGI middleware enforcing a maximum request body size.

    Two layers of defense:

      1. Header fast-path — if the client sent Content-Length and it
         exceeds the cap, respond 413 before reading any body bytes.
         Browsers / curl / fetch always set Content-Length on POSTs,
         so this covers the realistic attack vectors with a clean
         error response.

      2. Stream cap — if Content-Length is missing (chunked transfer)
         or the client lied, wrap receive() to count actual body bytes
         and abort the connection once the cap is exceeded. The handler
         sees a ClientDisconnect — no clean 413 in this case, but the
         server's memory stays bounded.
    """

    def __init__(self, app: Any, *, max_body_size: int) -> None:
        self.app = app
        self.max_body_size = max_body_size

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    break
                if declared > self.max_body_size:
                    await _send_413(send, self.max_body_size)
                    return
                break

        bytes_received = 0
        max_size = self.max_body_size

        async def receive_with_limit() -> Any:
            nonlocal bytes_received
            message = await receive()
            if message.get("type") == "http.request":
                bytes_received += len(message.get("body", b""))
                if bytes_received > max_size:
                    # Can't cleanly inject a 413 from inside receive —
                    # disconnect the body stream so the handler aborts
                    # instead of buffering more bytes. The client sees
                    # a torn connection (acceptable; rare path).
                    return {"type": "http.disconnect"}
            return message

        await self.app(scope, receive_with_limit, send)


async def _send_413(send: Any, max_body_size: int) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    body = json.dumps(
        {"detail": f"request body too large (max {max_body_size} bytes)"}
    ).encode()
    await send({"type": "http.response.body", "body": body})


app = FastAPI(
    title="auto-appeal-agent API",
    description="Prior Authorization Auto-Appeal Agent — backend",
    version="0.1.0",
)

# Body size cap goes BEFORE CORS so even unauthenticated cross-origin
# preflight + body floods are rejected without buffering.
app.add_middleware(BodySizeLimitMiddleware, max_body_size=MAX_REQUEST_BODY_BYTES)

# Next.js dev server runs on :3000; allow it to call us.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/cases", dependencies=[Depends(require_api_key)])
async def list_cases() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    if not FIXTURES_ROOT.exists():
        return {"cases": []}

    for case_dir in sorted(FIXTURES_ROOT.iterdir()):
        if not case_dir.is_dir() or not case_dir.name.startswith("case_"):
            continue
        entry: dict[str, Any] = {"case_id": case_dir.name}
        expected_path = case_dir / "expected.json"
        if expected_path.exists():
            try:
                data = json.loads(expected_path.read_text(encoding="utf-8"))
                entry["expected_appeal"] = data.get("expected_appeal", {})
            except json.JSONDecodeError:
                pass
        cases.append(entry)
    return {"cases": cases}


@app.get("/api/case/{case_id}/source/{kind}", dependencies=[Depends(require_api_key)])
async def get_source_text(case_id: str, kind: str) -> dict[str, str]:
    case_dir = _resolve_case_dir(case_id)
    if not case_dir.is_dir():
        raise HTTPException(status_code=404, detail="case not found")

    if kind == "patient_chart":
        path = case_dir / "patient_chart.txt"
        if not path.exists():
            raise HTTPException(status_code=404, detail="file not found")
        return {"text": path.read_text(encoding="utf-8")}

    if kind in ("denial_letter", "payer_policy"):
        path = case_dir / f"{kind}.pdf"
        if not path.exists():
            raise HTTPException(status_code=404, detail="file not found")
        return {"text": extract_text(path)}

    raise HTTPException(status_code=400, detail="invalid source kind")


_SAFE_FILENAME_CHARS = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_."
)


def _safe_filename(case_id: str) -> str:
    """Build a Content-Disposition filename from `case_id` that cannot
    inject HTTP headers.

    Why this exists: case_id is user-controlled (part of the
    POST /api/export_pdf body's AppealDraft.case_id). Interpolating
    it raw into the Content-Disposition header would let an attacker
    submit `case_id = "x\\r\\nContent-Type: text/html"` and inject
    response headers — letting browsers reinterpret the body, which
    opens XSS / cache-poisoning paths.

    We restrict the filename to a safe ASCII subset (alnum + `-_.`)
    and truncate to 64 chars. Anything outside the safe set becomes
    `_`. Robust by construction — header injection is impossible
    because the whitelist contains no CR/LF/quotes/semicolons.
    """
    sanitized = "".join(
        c if c in _SAFE_FILENAME_CHARS else "_" for c in case_id
    )[:64]
    if not sanitized:
        sanitized = "appeal"
    return f"{sanitized}_appeal.pdf"


@app.post("/api/export_pdf", dependencies=[Depends(require_api_key)])
async def export_pdf(draft: AppealDraft, request: Request) -> Response:
    """Render the (possibly edited) appeal draft to a PDF download.

    Accepts an AppealDraft whose paragraphs may have been edited by the
    user in the UI. Returns an application/pdf body with a filename
    suggestion based on case_id (sanitized — see _safe_filename).

    Rate-limited per-IP via the PDF bucket: PDF rendering is CPU-only
    (no Claude calls), so this bucket is intentionally looser than
    /api/run's bucket. Without a limit, an authenticated client could
    loop max-size drafts (50 paragraphs × 20KB) and peg the worker.
    """
    client_ip = _require_client_ip(request)
    await _enforce_rate_limit(
        client_ip,
        log=_pdf_rate_log,
        lock=_pdf_rate_lock,
        max_in_window=PDF_RATE_LIMIT_MAX,
        window_seconds=PDF_RATE_LIMIT_WINDOW_SECONDS,
    )
    pdf_bytes = render_appeal_pdf(draft)
    filename = _safe_filename(draft.case_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/run/{case_id}", dependencies=[Depends(require_api_key)])
async def run_case(case_id: str, request: Request) -> EventSourceResponse:
    case_dir = _resolve_case_dir(case_id)
    if not case_dir.is_dir():
        raise HTTPException(status_code=404, detail="case not found")

    # Per-IP rate limit BEFORE the per-case lock, so a flood from a
    # single IP gets 429'd before we even consider concurrency. Use
    # request.client.host as the limit key. Behind a reverse proxy,
    # consider X-Forwarded-For (left to deployment config; defaults
    # here are safe for direct/loopback usage).
    client_ip = _require_client_ip(request)
    await _enforce_rate_limit(
        client_ip,
        log=_run_rate_log,
        lock=_run_rate_lock,
        max_in_window=RATE_LIMIT_MAX_STARTS,
        window_seconds=RATE_LIMIT_WINDOW_SECONDS,
    )

    # Per-case concurrency guard — reject a second request for the
    # same case_id while the first is still running. Prevents two
    # browser tabs / two clicks from each spawning their own ~$1
    # pipeline. We do a CHEAP check here (just to return a clean 409
    # at the HTTP level for non-browser clients like curl); the
    # actual atomic acquire-and-add happens inside event_stream so
    # there's no window where the slot is held without a finally to
    # release it. Without this in-generator atomic swap, an exception
    # raised between `add()` and the generator's first yield would
    # leak the slot until process restart.
    if case_id in _active_pipelines:
        raise HTTPException(
            status_code=409,
            detail=(
                "a pipeline for this case is already running; "
                "wait for it to finish or cancel it first"
            ),
        )

    async def event_stream():
        # Atomic check-and-add at generator entry. From here on, the
        # only path that releases the slot is the finally block at the
        # bottom of this generator, which Python guarantees runs once
        # the generator has been started (even on client disconnect /
        # cancellation / unhandled exception). If another request
        # raced us between the route's cheap pre-check and here, emit
        # an SSE error event instead of an HTTP 409 — we already
        # started streaming, so the status code is committed.
        async with _active_pipelines_lock:
            if case_id in _active_pipelines:
                yield {
                    "data": json.dumps(
                        {
                            "stage": "error",
                            "error_type": "PipelineConflict",
                            "message": (
                                "a pipeline for this case is already running; "
                                "wait for it to finish or cancel it first"
                            ),
                        }
                    )
                }
                return
            _active_pipelines.add(case_id)

        # Build PipelineInput INSIDE the try below so a PipelineInput
        # validation failure can't leak the slot.
        # Queue bridges the worker thread (where run_pipeline executes)
        # and this asyncio coroutine (which yields SSE events).
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        loop = asyncio.get_event_loop()
        # Cooperative cancel signal. Set in the finally block below
        # whenever this stream ends — whether the pipeline finished
        # normally, errored, or the client disconnected (asyncio
        # raises CancelledError on the active yield). The orchestrator
        # checks this between every agent and aborts at the next
        # boundary, capping wasted spend at one in-flight Claude call
        # instead of running the remaining 4-5 agents on a gone client.
        cancel_event = threading.Event()

        def progress_cb(event: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        async def runner() -> None:
            try:
                pipeline_input = PipelineInput(
                    case_id=case_id,
                    denial_letter_path=str(case_dir / "denial_letter.pdf"),
                    patient_chart_path=str(case_dir / "patient_chart.txt"),
                    payer_policy_path=str(case_dir / "payer_policy.pdf"),
                )
                verified = await asyncio.to_thread(
                    run_pipeline,
                    pipeline_input,
                    progress_cb,
                    False,  # second_pass
                    cancel_event,
                )
                await queue.put(
                    {"stage": "done", "result": verified.model_dump()}
                )
            except PipelineCancelled:
                # Client disconnected. The queue consumer is already
                # gone; no point emitting an error event. Just exit
                # cleanly so the task's done() flips True.
                logger.info("pipeline cancelled by client disconnect")
            except Exception as exc:  # pragma: no cover - streamed to client
                # Log the full traceback (with any PHI in field values
                # echoed by Pydantic ValidationError) ONLY server-side.
                # The browser receives a generic message — no member
                # IDs, file paths, or chart fragments leak to client
                # devtools, screen shares, or browser logs. error_type
                # (the exception class name) is safe to expose and
                # helps the user know whether it's worth retrying.
                logger.exception(
                    "pipeline error case_id=%s error_type=%s",
                    case_id,
                    type(exc).__name__,
                )
                await queue.put(
                    {
                        "stage": "error",
                        "error_type": type(exc).__name__,
                        "message": (
                            "Pipeline failed. Please retry; "
                            "if the issue persists, check server logs."
                        ),
                    }
                )

        task = asyncio.create_task(runner())
        try:
            while True:
                event = await queue.get()
                yield {"data": json.dumps(event)}
                if event.get("stage") in ("done", "error"):
                    break
        finally:
            # Whether we got here via normal completion (break above),
            # an exception inside the generator, or asyncio raising
            # CancelledError on a yield because the client closed the
            # connection, we ALWAYS signal the worker thread to stop
            # at its next agent boundary. This is the $-saving step.
            cancel_event.set()
            # Best-effort shutdown wait. If the worker is mid-Claude-
            # call (40s LetterWriter with thinking is the realistic
            # worst case), we cannot interrupt the thread — let it
            # finish in the background, it'll see cancel_event when
            # it returns. Don't block the response handler past 1s.
            if not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
                except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                    pass
            # Free the case so the user (or another tab) can re-run
            # it. Done last so a stuck shutdown doesn't leak a slot.
            async with _active_pipelines_lock:
                _active_pipelines.discard(case_id)

    return EventSourceResponse(event_stream())
