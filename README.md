# auto-appeal-agent

Prior Authorization Auto-Appeal Agent — built with Claude Opus 4.7

## What it does

When an insurance company denies a medical treatment, a doctor can appeal —
but writing a watertight appeal takes hours of reading denial letters,
medical policies, patient charts, and clinical guidelines. Most doctors
don't have that time, so many appeals never get filed, and patients wait
for care they should have received.

This project turns that hours-of-physician-time into **minutes of agent
time**. It ingests the three documents an appeal needs — the denial
letter, the patient's chart, and the insurer's medical policy — and
produces a fully-cited appeal letter where **every factual claim is
verified against its source**. Nothing that can't be verified ships.

Not sure what "prior authorization" or "denial letter" means? See
[docs/GLOSSARY.md](docs/GLOSSARY.md). Curious why this specific problem
and not something else? See [docs/WHY.md](docs/WHY.md).

## Architecture

Six cooperating specialist agents plus a Verifier that catches
hallucinated citations before anything is sent:

```
Orchestrator
 ├─ DenialAnalyzer    (vision → denial codes, reasons, plan refs)
 ├─ PolicyReader      (payer medical-necessity criteria)
 ├─ ChartMiner        (1M-context chart → evidence matching criteria)
 ├─ GuidelineCiter    (clinical guidelines → supporting citations)
 ├─ LetterWriter      (draft appeal with citation markers)
 └─ Verifier          re-reads every citation; unverified claims never ship
```

A full plain-language walkthrough of each stage lives in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.template .env   # then paste your ANTHROPIC_API_KEY
```

## Generate the synthetic test cases

```bash
make fixtures           # writes five cases into fixtures/case_*/
```

Fixture directories are git-ignored and regenerable on demand. The
generator is pure code, so the fixtures are reproducible.

## Run tests

```bash
pytest                  # all tests
pytest -m "not integration"   # skip API-calling tests
```

## Project status

- **Phase 0 (done):** scaffold, schemas, stubbed agents, orchestrator
  wiring, 5 synthetic fixture cases, 27 green tests.
- **Phase 1 (next):** replace each stub with a real Claude Opus 4.7
  call, gated by the test suite.
- **Phase 2 (planned):** harden the Verifier (fuzzy matching, second-pass
  independent model); add a simple UI for the demo.

## Repository layout

```
auto-appeal-agent/
├── src/auto_appeal_agent/
│   ├── schemas.py             # Pydantic contracts between every stage
│   ├── orchestrator.py        # runs the pipeline
│   ├── agents/                # one module per specialist
│   └── scripts/
│       └── generate_fixtures.py
├── tests/
│   ├── test_schemas.py
│   ├── test_orchestrator.py
│   └── test_fixtures.py
├── fixtures/                  # generated; git-ignored
└── docs/
    ├── WHY.md
    ├── ARCHITECTURE.md
    └── GLOSSARY.md
```
