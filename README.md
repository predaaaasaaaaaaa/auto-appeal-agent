# auto-appeal-agent

Prior Authorization Auto-Appeal Agent — built with Claude Opus 4.7

## What it does

When a health insurance plan denies a medical treatment, a doctor can
appeal — but writing a watertight appeal takes hours of reading denial
letters, medical policies, patient charts, and clinical guidelines.
Most doctors don't have that time, so many appeals never get filed,
and patients wait for care they should have received.

This project turns hours-of-physician-time into **minutes of agent
time**. It reads the three documents an appeal needs — the denial
letter, the patient's chart, and the insurer's medical policy — and
produces a fully-cited appeal letter in which **every factual claim
is verified against its source document**. Anything that cannot be
verified is automatically stripped out before the letter ships.

The final letter ships with an audit page at the back: every quoted
claim is listed alongside the verbatim quote and the source it came
from. A clinician (or a reviewing attorney) can re-check the AI's
work end-to-end without leaving the page.

Not sure what "prior authorization" or "denial letter" means? See
[docs/GLOSSARY.md](docs/GLOSSARY.md). Curious why this specific
problem and not something else? See [docs/WHY.md](docs/WHY.md).

## What "every factual claim is verified" actually means

Each pipeline stage that reads a document also captures **verbatim
source quotes** — short snippets of the original text. The
LetterWriter produces a draft in which every clinical or policy
claim carries a `CitationMarker` pointing at one of those quotes.
The Verifier then runs a fresh, independent pass: for every
CitationMarker it does a substring match of the cited text against
the original quote. Anything that doesn't match is rejected and
physically removed from the letter — the audit page lists the
rejection so a human can see what was caught.

The four kinds of source the Verifier substring-checks against:

| Source                 | Where the quotes come from                              |
|------------------------|---------------------------------------------------------|
| `denial_letter`        | The insurer's denial PDF (read with vision)             |
| `payer_policy`         | The plan's medical-necessity policy PDF                 |
| `patient_chart`        | The patient's chart                                      |
| `clinical_guideline`   | A local corpus of professional-society guideline excerpts |

The clinical-guideline corpus is what closes the previous reliability
gap where guideline citations were drawn from Claude's training and
unverifiable. Now they live alongside the other three.

## Architecture

Six cooperating specialist agents plus a Verifier that catches
hallucinated citations before anything is sent:

```
Orchestrator
 ├─ DenialAnalyzer    (vision → denial codes, reasons, plan refs)
 ├─ PolicyReader      (payer medical-necessity criteria)
 ├─ ChartMiner        (1M-context chart → evidence matching criteria)
 ├─ GuidelineCiter    (corpus excerpts → supporting citations)
 ├─ LetterWriter      (draft appeal with citation markers)
 └─ Verifier          re-reads every citation; unverified claims never ship
```

A plain-language walkthrough of each stage lives in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Reliability & security posture

The system is hackathon scope, but the input/output and process
boundaries that touch user-controlled data, money, or PHI are
hardened — not because compliance demands it (real HIPAA deployment
needs much more, see below), but because in healthcare those
boundaries are exactly where the model going off the rails hurts
people. Every primitive below is exercised by the test suite.

**Pipeline integrity**

- **Verifier strips unverified citations** — every `CitationMarker`
  is substring-checked against its source quote; anything that fails
  is removed from the rendered letter and listed in the audit page.
- **Corpus-backed guideline citations** — guideline references are
  picked from a local corpus and substring-checked, not generated
  freely from training data.
- **Independent second-pass review (optional)** — a fresh-context
  reviewer agent grades each citation as `supports` / `partial` /
  `unsupported` and flags higher-level concerns; advisory only,
  never blocks shipping.

**Cost & abuse**

- **No auto-burn on case open.** Loading a case page does NOT start
  the pipeline. Users explicitly click **Start** — until then, no
  Anthropic call is made.
- **Cooperative cancellation.** Cancel button (and tab close)
  triggers a server-side cancel signal; the orchestrator aborts at
  the next agent boundary. Worst-case wasted spend: one in-flight
  Claude call.
- **Per-case concurrency lock.** A second `/api/run` request for an
  in-flight case returns 409 instead of spawning a parallel pipeline.
  Slot release is guaranteed via the SSE generator's `finally`.
- **Per-IP sliding-window rate limit.** `/api/run` (5 starts / 60s
  by default) and `/api/export_pdf` (20 renders / 60s) get
  independent buckets — different cost profiles, different ceilings.
  Tunable via env.
- **Body-size cap (2 MiB default).** ASGI middleware rejects oversize
  requests with 413 before any Pydantic deserialization runs, so a
  500 MB JSON blob can't exhaust memory before validation kicks in.
- **Pydantic field-length bounds.** Every user-controllable string
  in `AppealDraft` (case_id, paragraph text, etc.) is capped at
  generous-but-finite values to defend the PDF renderer.

**API surface**

- **Optional shared-key auth.** Set `APPEAL_API_KEY` to require
  `X-API-Key` on every cost / data endpoint. Constant-time comparison
  via `secrets.compare_digest`. Unset = open dev mode with a startup
  warning.
- **Path-traversal scrub on `case_id`.** Resolved + boundary-checked
  against `fixtures/`; out-of-tree paths get 404 (no error echo).
- **Content-Disposition filename whitelist.** PDF download filename
  is restricted to `[A-Za-z0-9_.-]` so a malicious `case_id` cannot
  inject HTTP headers.
- **`Literal` enum on source-kind parameter.** `/api/case/{id}/source/{kind}`
  accepts only `patient_chart | denial_letter | payer_policy`,
  enforced at the FastAPI schema layer (422 for anything else).
- **Tight CORS.** Origins limited to `localhost:3000` / `127.0.0.1:3000`,
  methods to GET / POST / OPTIONS, headers to `Content-Type` and
  `X-API-Key`. `allow_credentials=False` pinned explicitly.
- **No PHI in client-facing errors.** `str(exception)` is never
  streamed to the browser; the server logs the full traceback,
  the client gets a generic message + the exception class name.

**Prompt safety**

- **Defense-in-depth against prompt injection.** Every user-controlled
  input that splices into a Claude prompt (patient charts, denial
  letters, payer policies, draft letters) is wrapped in XML data
  tags — `<patient_chart>...</patient_chart>` etc. — and the system
  prompt explicitly instructs the model to treat tag contents as
  data, never instructions. Closing-tag collisions inside user data
  are mangled so an attacker cannot break out of the wrapper.

**What this is not yet**

This is hackathon scope, not a HIPAA-compliant healthcare deployment.
The above is the application-layer hardening; production needs the
infrastructure layer too — see *What V1 deliberately leaves out*
below.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.template .env   # then paste your ANTHROPIC_API_KEY

# UI dependencies (one-time)
cd ui && PATH="$HOME/.local/node/bin:$PATH" npm install
cd ..
```

### Required env vars

| Variable               | Purpose                                              |
|------------------------|------------------------------------------------------|
| `ANTHROPIC_API_KEY`    | Your Claude API key — every agent call uses it.      |

### Optional env vars

| Variable                          | Default                  | Purpose                                       |
|-----------------------------------|--------------------------|-----------------------------------------------|
| `ANTHROPIC_MODEL`                 | `claude-opus-4-7`        | Override the model used by every agent.       |
| `LOG_LEVEL`                       | `INFO`                   | Server log verbosity.                         |
| `APPEAL_API_KEY`                  | unset (open mode)        | When set, every cost / data endpoint requires `X-API-Key`. **Required for any non-loopback deployment.** |
| `NEXT_PUBLIC_APPEAL_API_KEY`      | unset                    | Same key, exposed to the browser bundle so the UI can attach it. NEXT_PUBLIC vars are public — production should hide this behind a server-side proxy. |
| `NEXT_PUBLIC_API_BASE_URL`        | `http://localhost:8000`  | Direct FastAPI URL for the browser EventSource. Bypasses the Next.js dev rewrite proxy, which buffers `text/event-stream` responses and breaks live progress display. |
| `RATE_LIMIT_WINDOW_SECONDS`       | `60`                     | Sliding-window length on `/api/run`.          |
| `RATE_LIMIT_MAX_STARTS`           | `5`                      | Max pipeline starts per IP per window.        |
| `PDF_RATE_LIMIT_WINDOW_SECONDS`   | `60`                     | Sliding-window length on `/api/export_pdf`.   |
| `PDF_RATE_LIMIT_MAX`              | `20`                     | Max PDF renders per IP per window.            |
| `MAX_REQUEST_BODY_BYTES`          | `2097152` (2 MiB)        | Upper bound on request body size; oversize → 413. |

## Generate the synthetic test cases

```bash
make fixtures           # writes five cases into fixtures/case_*/
```

Fixture directories are regenerable on demand. The generator is pure
code, so the fixtures are byte-deterministic.

## Run the demo

Two commands in two terminals:

```bash
make api    # FastAPI backend on :8000
make ui     # Next.js frontend on :3000
```

Then open <http://localhost:3000> and:

1. **Browse the worklist** — click into any case to see its denial
   letter, patient chart, and payer policy in the source pane. No
   pipeline runs yet (no Anthropic call burned).
2. **Click `Start pipeline →`** when you actually want to draft.
   Six agents run in sequence (~90–120 s, ~$1 on Opus 4.7). The
   right pane shows a live waiting panel: each agent flips
   `pending → running → done` with per-stage elapsed time and an
   overall progress bar.
3. **Cancel any time.** The Cancel button (or closing the tab)
   stops the pipeline at the next agent boundary; one in-flight
   Claude call still completes, the rest are skipped.
4. **Edit the draft inline.** When the pipeline finishes, the
   editable letter appears with citation chips you can click —
   each opens the source pane and highlights the verbatim quote.
   Verified citations are green ✓; rejected ones are listed in a
   red panel beneath.
5. **`Download PDF`** renders the (possibly edited) draft to a
   physician-signable PDF with a citations audit appendix.

## Run the tests

```bash
make test                # fast, replay-only, no API spend
make test-integration    # integration tests; calls the real API
make record-cassettes    # re-record every cassette against the live API
make probe-case-01       # cheap one-case live probe (~$0.50–$1)
```

## What V1 deliberately leaves out

This is a demo of an architecture, not a production deployment.
Things a real-world deployment would need that V1 does not include:

- **HIPAA-compliant infrastructure.** V1 has the application-layer
  hardening listed above (auth, rate limiting, prompt-injection
  defenses, no client-side PHI in errors, etc.) but does not have
  encryption-at-rest, BAA-covered hosting, audit logging that
  survives process restart, structured access controls, or PHI
  retention / minimization policies. Real deployment needs all of
  those plus a legal review.
- **Real EHR / FHIR integration.** V1 reads from PDFs and a plain-text
  chart. Real deployment needs FHIR connectors, OAuth flows, and
  vendor-specific tenant onboarding (Epic, Cerner, Athena).
- **Licensed verbatim guideline text.** The guideline corpus shipped
  in `fixtures/guidelines/corpus.json` paraphrases real published
  recommendations. The architecture is unchanged when the corpus is
  swapped for licensed verbatim text from each guideline (UpToDate,
  the society's open-access publication, or a licensed vendor).
- **Initial PA submission.** V1 handles the appeal (post-denial); it
  does not handle the original prior-authorization submission.
- **Production-grade auth.** The shared-key auth is rotation-friendly
  but has no users, sessions, or token expiry. Production needs
  SSO / OAuth / per-user sessions on top of (or instead of) the
  pre-shared key.

These aren't laziness — they're real engineering and legal
multi-week tracks. The hackathon submission is the architecture, the
reliability primitives, and the application-layer hardening;
production-readiness is the next chapter.

## Repository layout

```
auto-appeal-agent/
├── src/auto_appeal_agent/
│   ├── schemas.py              # Pydantic contracts between every stage
│   ├── orchestrator.py         # runs the pipeline
│   ├── anthropic_client.py     # cached, structured-output Claude wrapper
│   ├── guideline_corpus.py     # local corpus loader for GuidelineCiter
│   ├── pdf_export.py           # appeal-letter → PDF renderer
│   ├── prompt_safety.py        # XML-tag wrapping + injection guardrail
│   ├── api/                    # FastAPI backend (SSE pipeline streaming)
│   ├── agents/                 # one module per specialist
│   └── scripts/
│       └── generate_fixtures.py
├── tests/
│   ├── cassettes/              # recorded API responses for replay
│   └── test_*.py
├── fixtures/
│   ├── case_*/                 # synthetic test cases (generated)
│   └── guidelines/corpus.json  # local clinical-guideline corpus
├── ui/                         # Next.js frontend (run page, edit, PDF)
└── docs/
    ├── WHY.md
    ├── ARCHITECTURE.md
    └── GLOSSARY.md
```
