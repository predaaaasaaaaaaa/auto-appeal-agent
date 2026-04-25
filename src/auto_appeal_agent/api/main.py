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
import threading
from pathlib import Path
from typing import Any

# Configure root logging so auto_appeal_agent.* loggers surface in
# the uvicorn terminal. LOG_LEVEL env var (from .env) wins if set;
# otherwise INFO is sensible for live diagnosis.
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sse_starlette.sse import EventSourceResponse

from auto_appeal_agent.orchestrator import PipelineCancelled, run_pipeline
from auto_appeal_agent.pdf_export import render_appeal_pdf
from auto_appeal_agent.pdf_utils import extract_text
from auto_appeal_agent.schemas import AppealDraft, PipelineInput

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_ROOT = REPO_ROOT / "fixtures"

app = FastAPI(
    title="auto-appeal-agent API",
    description="Prior Authorization Auto-Appeal Agent — backend",
    version="0.1.0",
)

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


@app.get("/api/cases")
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


@app.get("/api/case/{case_id}/source/{kind}")
async def get_source_text(case_id: str, kind: str) -> dict[str, str]:
    case_dir = FIXTURES_ROOT / case_id
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


@app.post("/api/export_pdf")
async def export_pdf(draft: AppealDraft) -> Response:
    """Render the (possibly edited) appeal draft to a PDF download.

    Accepts an AppealDraft whose paragraphs may have been edited by the
    user in the UI. Returns an application/pdf body with a filename
    suggestion based on case_id.
    """
    pdf_bytes = render_appeal_pdf(draft)
    filename = f"{draft.case_id}_appeal.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/run/{case_id}")
async def run_case(case_id: str) -> EventSourceResponse:
    case_dir = FIXTURES_ROOT / case_id
    if not case_dir.is_dir():
        raise HTTPException(status_code=404, detail="case not found")

    pipeline_input = PipelineInput(
        case_id=case_id,
        denial_letter_path=str(case_dir / "denial_letter.pdf"),
        patient_chart_path=str(case_dir / "patient_chart.txt"),
        payer_policy_path=str(case_dir / "payer_policy.pdf"),
    )

    async def event_stream():
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
                await queue.put(
                    {
                        "stage": "error",
                        "error_type": type(exc).__name__,
                        "message": str(exc),
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

    return EventSourceResponse(event_stream())
