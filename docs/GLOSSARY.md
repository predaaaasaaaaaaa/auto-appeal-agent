# Glossary

Terms you'll see in the code, docs, and fixtures.

## Insurance / healthcare terms

**Prior Authorization (PA, "prior auth")** — A requirement from your
insurance company to get their approval *before* they will pay for a
treatment. If they say no, the doctor can either give up or file an
appeal.

**Denial Letter** — The document the insurance company sends when they
refuse to pay. It says who the patient is, what was requested, why the
insurer said no, and the code(s) they cited.

**Appeal** — The doctor's response to a denial. It is a formal letter
arguing that the insurer's denial was wrong (or that the insurer missed
relevant facts), usually citing the insurer's own medical policy, the
patient's chart, and clinical guidelines.

**Medical Necessity** — The legal standard insurers use to decide whether
something should be covered. A treatment is "medically necessary" when,
per the insurer's own policy, the patient meets certain criteria. Most
denials cite "not medically necessary" as the reason.

**Payer / Insurer / Plan** — All mean roughly "the company paying the
bill." We use `payer` in code for precision.

**Payer Policy / Medical Policy** — A published document from an insurer
listing the exact criteria a patient must meet for a given treatment to
be covered. They are often 5–20 pages long and full of legal language.

**Step Therapy** — A common policy requirement: you must try the cheaper
treatment first and have it fail (or be intolerable to you) before the
insurer will pay for the more expensive one.

**Formulary** — The list of drugs an insurance plan will cover. A drug
"not on formulary" is not covered and has to be specially approved.

**Clinical Guidelines** — Recommendations published by professional
medical societies (American Diabetes Association, American College of
Rheumatology, etc.) describing the standard of care for a condition.
They are not legally binding, but citing them strengthens an appeal.

**Patient Chart / Medical Record** — The full record of a patient's
visits, diagnoses, labs, medications, imaging, and notes. Can run to
hundreds of pages.

## Clinical terms that appear in our fixture cases

**BMI (Body Mass Index)** — A rough measure of body fat based on weight
and height. BMI ≥ 30 is "obese."

**A1c (Hemoglobin A1c)** — A blood test showing average blood-sugar over
the prior 2–3 months. Normal is under 5.7%. Diabetes is diagnosed at 6.5%
or above. Poorly controlled diabetes is generally 8%+.

**DAS28** — Disease Activity Score in 28 joints. A standard measure of
rheumatoid arthritis activity. Below 2.6 is remission; 2.6–3.2 is low;
3.2–5.1 is moderate; above 5.1 is high.

**DASH Score** — Disabilities of the Arm, Shoulder and Hand. A 0–100
functional score for upper-extremity disability. Higher = worse.

**CGM (Continuous Glucose Monitor)** — A small wearable sensor that
tracks blood sugar continuously, replacing fingerstick tests.

**GLP-1 Receptor Agonist** — Class of drugs (semaglutide/Ozempic/Wegovy,
tirzepatide/Mounjaro, liraglutide/Victoza) used for type 2 diabetes and
weight management.

**DMARD (Disease-Modifying Antirheumatic Drug)** — Drugs for rheumatoid
arthritis. "Conventional" DMARDs (methotrexate, hydroxychloroquine,
leflunomide) are older and cheaper. "Biologic" DMARDs (adalimumab/Humira,
etanercept, infliximab) are newer, more expensive, and typically require
step therapy.

**PT (Physical Therapy)** — Rehabilitation therapy. Insurance usually
covers a limited number of visits ("visits per episode of care").

**MTC (Medullary Thyroid Carcinoma), MEN2 (Multiple Endocrine Neoplasia
type 2)** — Rare endocrine cancers. They are contraindications to GLP-1
drugs, which is why GLP-1 policy documents always ask about them.

**CPT code, HCPCS code, ICD-10 code** — Standardized codes used in
billing. CPT describes the procedure done, HCPCS describes equipment
and services, ICD-10 describes the diagnosis.

## Project-internal terms

**Fixture** — A fake-but-realistic test case stored under `fixtures/`.
Each fixture is a folder containing a denial letter (PDF), a patient
chart (txt), a payer policy (PDF), and an `expected.json` describing
what a correct appeal should contain.

**SourceQuote** — A verbatim quote captured by an upstream agent from
one of the input documents, with a stable `quote_id` so later stages
can refer to it.

**CitationMarker** — A "receipt" attached to every factual claim in the
appeal draft, pointing by `source_id` at a SourceQuote.

**Verifier** — The pipeline stage that re-reads every CitationMarker
against its source and deletes anything it cannot confirm. The project's
reliability guarantee.

**Stub / Phase 0** — In Phase 0, every agent returns a valid but
placeholder-content response. This lets us build and test the pipeline
wiring before spending API credits on real LLM calls.
