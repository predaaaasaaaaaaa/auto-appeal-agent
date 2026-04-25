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

Then open <http://localhost:3000>, pick a case, and watch the
pipeline run live. When it finishes you can edit the draft in the
browser and click **Download PDF**.

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

- **Real EHR / FHIR integration.** V1 reads from PDFs and a plain-text
  chart. Real deployment needs FHIR connectors, OAuth flows, and
  vendor-specific tenant onboarding (Epic, Cerner, Athena).
- **HIPAA-compliant infrastructure.** V1 has no PHI safeguards,
  encryption-at-rest, audit logging, access controls, or BAA. Real
  deployment needs all of those plus legal review.
- **Licensed verbatim guideline text.** The guideline corpus shipped
  in `fixtures/guidelines/corpus.json` paraphrases real published
  recommendations. The architecture is unchanged when the corpus is
  swapped for licensed verbatim text from each guideline (UpToDate,
  the society's open-access publication, or a licensed vendor).
- **Initial PA submission.** V1 handles the appeal (post-denial); it
  does not handle the original prior-authorization submission.

These aren't laziness — they're real engineering and legal
multi-week tracks. The hackathon submission is the architecture and
the reliability primitives; production-readiness is the next chapter.

## Repository layout

```
auto-appeal-agent/
├── src/auto_appeal_agent/
│   ├── schemas.py              # Pydantic contracts between every stage
│   ├── orchestrator.py         # runs the pipeline
│   ├── anthropic_client.py     # cached, structured-output Claude wrapper
│   ├── guideline_corpus.py     # local corpus loader for GuidelineCiter
│   ├── pdf_export.py           # appeal-letter → PDF renderer
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
