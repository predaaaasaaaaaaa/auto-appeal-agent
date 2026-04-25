# How the agent works

## The short version

Think of the agent as a **small law firm** that writes appeal letters.
The firm has six specialists. Each one has a narrow job. They hand their
findings to the next specialist, and at the end, a very careful paralegal
(the **Verifier**) checks every single factual claim against the original
document before anything is sent.

If the paralegal cannot confirm a claim, that claim is deleted. This is
the reason a hallucinated citation never reaches the insurer.

## The pipeline

```
                          +-----------+
  denial letter (PDF)---->| Denial    |
                          | Analyzer  |
                          +-----+-----+
                                |
                                v
  payer policy (PDF)----->+-----------+
                          | Policy    |
                          | Reader    |
                          +-----+-----+
                                |
                                v
  patient chart (txt)---->+-----------+
                          | Chart     |
                          | Miner     |
                          +-----+-----+
                                |
                                v
                          +-----------+
                          | Guideline |
                          | Citer     |
                          +-----+-----+
                                |
                                v
                          +-----------+
                          | Letter    |
                          | Writer    |
                          +-----+-----+
                                |
                                v
                          +-----------+
                          | Verifier  |
                          +-----+-----+
                                |
                                v
                   VerifiedAppeal (final)
```

## What each specialist does

### 1. DenialAnalyzer — "What did the insurer say?"

Reads the denial letter and pulls out:
  - who the patient is,
  - what treatment was requested,
  - the exact reason(s) the insurer gave for refusing,
  - verbatim quotes from the letter (so the Verifier can re-read them).

### 2. PolicyReader — "What does the insurer's own rulebook require?"

Every insurer publishes medical policies. These policies list, in legal
language, the exact checkboxes a patient has to tick to qualify for a
given treatment. The PolicyReader turns that legal language into a
structured list of criteria ("the patient must be over 18", "the patient
must have BMI over 30", etc.).

### 3. ChartMiner — "Does the patient's chart actually tick those boxes?"

The patient's chart is the raw evidence. For each criterion the policy
requires, the ChartMiner hunts through the chart for matching evidence
(a lab value, a diagnosis, a date of a past treatment) and records the
verbatim quote from the chart that supports (or refutes) it.

### 4. GuidelineCiter — "What do the professional societies say?"

Professional societies (like the American Diabetes Association or the
American College of Rheumatology) publish clinical guidelines that tell
doctors what the standard of care is. Citing these guidelines strengthens
an appeal.

The GuidelineCiter does NOT generate guideline citations from the model's
training. It picks excerpts from a **local clinical-guideline corpus**
shipped under `fixtures/guidelines/corpus.json`. Each excerpt has a
stable id; the GuidelineCiter cites by id and emits the verbatim text
straight from the corpus. The downstream Verifier then substring-checks
the cited text against the corpus excerpt — exactly the same primitive
used for chart, denial-letter, and policy citations. A real-world
deployment would swap the corpus for licensed verbatim text from each
guideline (UpToDate, the society's open-access publication, or a
licensed vendor); this module's interface does not change.

### 5. LetterWriter — "Put it all together."

Takes everything the earlier specialists found and writes a professional
appeal letter. Every factual claim is tagged with a **CitationMarker** — a
receipt that says "this claim is backed by quote X from document Y."

### 6. Verifier — "Check every receipt."

This is the project's reliability guarantee. The Verifier ignores the
draft's prose and does its own pass: for every CitationMarker, it looks
at the original quote and confirms it actually appears there. Anything
that does not verify is **removed** from the letter and reported as a
`rejected_citation`. A letter only becomes "ready to send" when 100%
of citations verify.

## Why the extraction/verification split matters

It's tempting to ask one LLM to "write an appeal letter from these PDFs."
That would sometimes work, and sometimes silently produce a letter with
made-up BMI numbers or a fabricated citation to a guideline that doesn't
exist. In an appeal, a hallucinated fact gets the whole letter tossed.

By splitting extraction (LetterWriter) from verification (Verifier), and
by requiring the LetterWriter to emit a CitationMarker alongside every
claim, the Verifier has something very concrete to check. This is a
boring idea, but it's the difference between a demo and a product.

## Where the typed contracts live

Every stage of the pipeline reads and writes **Pydantic models**, not
free-form text. The models live in `src/auto_appeal_agent/schemas.py`.
If any agent returns a shape the next agent doesn't expect, the whole
pipeline raises a clear error instead of silently passing on garbage.

## Where the reliability tests live

`tests/test_schemas.py` checks that every shape is strict (unknown fields
rejected) and round-trips through JSON. `tests/test_orchestrator.py`
covers the Verifier's rejection logic directly. `tests/test_fixtures.py`
runs the full pipeline on each of the five synthetic cases.

As of Phase 0, all six agents are stubs that return valid shapes. Phase 1
replaces them with real Claude calls, one at a time, with the test suite
gating each change.
