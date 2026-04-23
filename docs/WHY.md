# Why this project exists

## The problem, in one sentence

**When people need medical care in the United States, they often wait. Those
waits get people sicker, which makes everything more expensive and slower,
which creates even longer waits.** Health-care researchers call this the
"delayed-care doom loop."

## What "delayed care" actually looks like

A patient sees their doctor. The doctor recommends a medication, a scan, a
surgery, or physical therapy. Before the insurance company will pay for it,
they require a step called **prior authorization**: the doctor has to prove,
on paper, that the treatment is "medically necessary" under that insurer's
rules.

Prior authorization was invented to control cost. In practice, it controls
access. Here is what happens over and over:

1. The doctor submits the request.
2. The insurer denies it — sometimes for a real reason, often for a technical
   one (missing documentation, wrong billing code, outdated policy version).
3. The doctor can appeal the denial, but a good appeal means reading the
   insurer's medical-policy document, cross-referencing the patient's entire
   chart, pulling in clinical guidelines, and writing a professional letter
   with citations. That is hours of physician time per patient.
4. So most appeals never get written. The treatment doesn't happen. The
   patient gets worse. The patient's condition becomes more expensive to
   treat. Everyone is angry.

The kicker: when doctors **do** appeal, they win about **83% of the time.**
The system would largely work if only physicians had the time.

## Our wager

If writing a watertight appeal drops from **hours of physician time to a few
minutes of agent time**, many more appeals get filed, many more are won,
patients get their treatments sooner, and the doom loop breaks — at least
for this one class of delay.

We are not trying to fix everything in healthcare. We are attacking one
specific, measurable, widely-hated bottleneck.

## Why this is a good fit for Claude Opus 4.7

Generating a correct appeal requires reading **several long documents at
once** — a denial letter, the insurer's full medical policy, and the
patient's chart, which can run to hundreds of pages — and finding the
handful of facts that matter. It also requires **not making anything up**.
A hallucinated citation in an appeal letter is worse than no appeal at all,
because the reviewing nurse will throw the whole letter out.

Opus 4.7 brings two capabilities that matter here:

- **1-million-token context** so the whole chart and the whole policy fit
  in one prompt.
- **High-resolution vision (2576-pixel images)** so we can read scanned
  denial letters and PDFs with numbers, stamps, and tiny footnotes intact.

And on top of that, we add the **Verifier**: an independent pass that
checks every factual claim in the draft letter against the original source,
and deletes anything it cannot confirm. The goal is not "impressive," it's
"correct."
