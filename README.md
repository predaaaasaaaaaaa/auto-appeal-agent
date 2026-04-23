# auto-appeal-agent

Prior Authorization Auto-Appeal Agent — built with Claude Opus 4.7 

## What it does
Ingests a denial letter, patient chart, and payer policy. Outputs a fully-cited appeal letter where **every factual claim is verified against its source**. Weeks of physician time → minutes.

## Architecture
```
Orchestrator
 ├─ DenialAnalyzer    (vision → denial codes, reasons, plan refs)
 ├─ PolicyReader      (payer medical-necessity criteria)
 ├─ ChartMiner        (1M-context chart → evidence matching criteria)
 ├─ GuidelineCiter    (clinical guidelines → supporting citations)
 ├─ LetterWriter      (draft appeal with citation markers)
 └─ Verifier          re-reads every citation; unverified claims never ship
```

## Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.template .env   # then paste your ANTHROPIC_API_KEY
```

## Run tests
```bash
pytest                  # all tests
pytest -m "not integration"   # skip API-calling tests
```
