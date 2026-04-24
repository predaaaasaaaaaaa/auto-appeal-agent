"""
Generate the 5 synthetic test cases the pipeline is graded against.

Plain-language summary: "fixtures" are fake-but-realistic example cases we
use as test inputs. Each case is a folder on disk that looks like a real
prior-authorization denial the agent might receive:

    fixtures/case_01_ozempic_bmi34/
      denial_letter.pdf     (what the insurer sent back)
      patient_chart.txt     (relevant history, diagnoses, labs)
      payer_policy.pdf      (the plan's medical-necessity criteria)
      expected.json         (what a correct appeal SHOULD contain)

Every piece of clinical/payer data in this file is FABRICATED. No real
patient information. Names, member IDs, plan names, policy numbers are
invented. Clinical values are plausible but made up.

Run:  .venv/bin/python -m auto_appeal_agent.scripts.generate_fixtures
Or:   make fixtures
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fpdf import FPDF

FIXTURES_ROOT = Path(__file__).resolve().parents[3] / "fixtures"


@dataclass
class FixtureCase:
    """One synthetic test case: three input files + expected appeal content."""

    case_id: str
    dir_name: str
    denial_letter_title: str
    denial_letter_text: str
    patient_chart_text: str
    payer_policy_title: str
    payer_policy_text: str
    expected_appeal: dict[str, Any] = field(default_factory=dict)


from datetime import datetime, timezone

# Pinned timestamp so every `make fixtures` run produces byte-identical
# PDFs. Without this, fpdf2 stamps datetime.now() into the PDF metadata
# and every regeneration dirties `git status` + invalidates any tool
# that hashes the fixture bytes.
_PINNED_CREATION = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _write_pdf(title: str, body_text: str, out_path: Path) -> None:
    """Render body_text into a simple single-column PDF at out_path.

    Output is byte-deterministic: the PDF metadata timestamp and producer
    are pinned so regenerating fixtures from the same source strings
    yields identical bytes.
    """
    pdf = FPDF(format="Letter")
    pdf.set_creation_date(_PINNED_CREATION)
    pdf.set_producer("auto-appeal-agent fixtures")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 13)
    pdf.multi_cell(0, 7, title)
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 11)
    for paragraph in body_text.strip().split("\n\n"):
        pdf.multi_cell(0, 5.5, paragraph)
        pdf.ln(2)
    pdf.output(str(out_path))


CASE_1 = FixtureCase(
    case_id="case_01_ozempic_bmi34",
    dir_name="case_01_ozempic_bmi34",
    denial_letter_title="BlueSun Health Plan - Prior Authorization Denial",
    denial_letter_text="""
Date: April 1, 2026

Member: Jane A. Doe
Member ID: BS-A1234567
Date of Birth: May 14, 1978
Plan: BlueSun Health Premium HMO
Provider: Dr. Maria Chen, MD (NPI 1234567890)

Dear Jane A. Doe:

We are writing to inform you that your prior authorization request for semaglutide (Ozempic) 1mg weekly subcutaneous injection has been DENIED.

Reason for denial: Not medically necessary. Member does not meet all criteria for GLP-1 receptor agonist therapy per plan medical policy MEDPOL-GLP1-v3 (effective January 1, 2026). Denial codes: MN-12, STEP-03.

Specifically: documentation does not establish that the member has completed the required six months of supervised diet, exercise, and behavior-modification program before pharmacologic therapy.

You have the right to appeal this decision within 180 days. Appeals should reference policy MEDPOL-GLP1-v3 and include supporting clinical documentation.

Sincerely,
BlueSun Health Plan
Medical Review Department
""".strip(),
    patient_chart_text="""
PATIENT CHART - Jane A. Doe
DOB: 1978-05-14  |  MRN: 00451892
PCP: Dr. Maria Chen, MD
Chart excerpt assembled 2026-04-02

--- PROBLEM LIST ---
Essential hypertension (I10) - diagnosed 2021
Type 2 diabetes mellitus without complications (E11.9) - diagnosed 2023
Obesity, class 2 (E66.01) - diagnosed 2024

--- ACTIVE MEDICATIONS ---
Lisinopril 10mg PO daily (since 2021)
Metformin 1000mg PO BID (since 2023)
Atorvastatin 20mg PO qHS (since 2024)

--- VITALS / LABS (last 12 months) ---
2025-04-10: BP 138/86, weight 208 lb, height 5'5", BMI 34.6
2025-10-05: BP 134/82, weight 206 lb, BMI 34.3
2026-02-15: BP 132/84, weight 205 lb, BMI 34.2, A1c 7.2%, LDL 108
2026-03-10: BP 130/82, weight 204 lb, BMI 34.0, A1c 7.1%

--- PROGRESS NOTE 2025-05-01 (Dr. Chen) ---
Patient enrolled in structured Weight Watchers program today. Dietitian referral placed. Plan for supervised lifestyle modification x 6+ months before considering pharmacotherapy.

--- PROGRESS NOTE 2025-11-20 (Dr. Chen) ---
Six-month lifestyle modification review. Patient has attended 21 of 24 scheduled Weight Watchers group sessions. Food logs submitted weekly. Exercise log shows 150+ minutes moderate activity per week. Weight change: 208 -> 206 lb (2 lb loss over 6 months). A1c remains 7.2%. Will continue lifestyle plus consider adjunct pharmacotherapy.

--- PROGRESS NOTE 2026-02-15 (Dr. Chen) ---
10-month review. Weight 205 lb (3 lb loss over 10 months). Patient expresses frustration with limited progress despite full compliance. Reviewed risks/benefits of GLP-1 RA therapy. No personal or family history of medullary thyroid carcinoma or MEN2 (confirmed with patient today). Not pregnant; last menstrual period 2026-02-06. Plan: submit prior authorization for semaglutide.

--- PROGRESS NOTE 2026-03-10 (Dr. Chen) ---
Following PA denial. Patient has completed 10 months of documented structured lifestyle intervention (Weight Watchers attendance records on file). All GLP-1 RA eligibility criteria met per plan policy. Will file appeal.
""".strip(),
    payer_policy_title="MEDPOL-GLP1-v3: GLP-1 Receptor Agonists for Weight Management",
    payer_policy_text="""
BlueSun Health Medical Policy
Policy Number: MEDPOL-GLP1-v3
Effective Date: January 1, 2026
Last Reviewed: December 15, 2025

SCOPE: This policy governs coverage of glucagon-like peptide-1 (GLP-1) receptor agonists (semaglutide, liraglutide, tirzepatide) when prescribed for weight management in adult members.

MEDICAL NECESSITY CRITERIA. All of the following must be met and documented in the medical record:

1. Age at least 18 years.

2. Body Mass Index (BMI) at or above 30 kg/m^2, OR BMI at or above 27 kg/m^2 with at least one weight-related comorbidity (hypertension, type 2 diabetes mellitus, dyslipidemia, or obstructive sleep apnea).

3. Documented participation in a supervised program of reduced-calorie diet, increased physical activity, and behavior modification for a minimum of six months with objective measures of compliance.

4. Absence of contraindications, specifically: personal or family history of medullary thyroid carcinoma; personal history of multiple endocrine neoplasia type 2; pregnancy or active plans for pregnancy.

STEP THERAPY REQUIREMENT: Before approval of tirzepatide or the obesity-specific formulations of semaglutide, members must have a documented trial and inadequate response to at least one generic or preferred alternative pharmacotherapy, unless clinically contraindicated.

REAUTHORIZATION: Approvals are granted for 6 months. Continued coverage requires documented weight loss of at least 5% of baseline body weight.
""".strip(),
    expected_appeal={
        "key_claims": [
            "Patient's BMI is 34.2, exceeding the policy threshold of 30.",
            "Patient has documented 10 months of supervised Weight Watchers program (exceeds 6-month requirement).",
            "Patient has no contraindications (no MTC, MEN2, pregnancy).",
            "Patient has multiple qualifying comorbidities (HTN, T2DM).",
        ],
        "must_cite_source_types": [
            "payer_policy",
            "patient_chart",
        ],
    },
)

CASE_2 = FixtureCase(
    case_id="case_02_brain_mri_headache",
    dir_name="case_02_brain_mri_headache",
    denial_letter_title="Northstar Insurance - Prior Authorization Denial",
    denial_letter_text="""
Date: March 28, 2026

Member: Robert K. Lee
Member ID: NS-77881266
Date of Birth: October 3, 1984
Plan: Northstar Gold PPO
Ordering Provider: Dr. Samir Patel, MD (Neurology)

Dear Mr. Lee:

Your request for an MRI of the brain with and without contrast (CPT 70553) has been DENIED.

Reason for denial: Request does not meet medical necessity criteria for advanced imaging in the evaluation of headache per Northstar Imaging Policy IMG-HEAD-v7. The submitted documentation does not demonstrate presence of red-flag features or failure of first-line management sufficient to justify advanced imaging at this time.

Denial code: IMG-N-04 (insufficient clinical red flags documented).

You have the right to appeal. Appeals must reference the specific red-flag criteria in policy IMG-HEAD-v7 and include supporting clinical documentation.

Northstar Insurance
Utilization Management
""".strip(),
    patient_chart_text="""
PATIENT CHART - Robert K. Lee
DOB: 1984-10-03  |  MRN: 00882341
Treating provider: Dr. Samir Patel, MD, Neurology
Chart excerpt assembled 2026-03-29

--- PROBLEM LIST ---
Chronic migraine without aura (G43.709) - diagnosed 2023
New-onset focal neurologic symptoms (R41.89) - 2026-03

--- PROGRESS NOTE 2025-09-12 (Dr. Patel) ---
Established migraine. On topiramate 50mg BID with partial benefit. Continues 2-3 migraines per month. No aura. Plan: continue current therapy, consider CGRP mAb if inadequate response.

--- PROGRESS NOTE 2026-01-20 (Dr. Patel) ---
Added erenumab 70mg monthly. Patient reports 4-6 migraines/month now, down from baseline. No red flags. No imaging indicated.

--- URGENT CARE VISIT 2026-03-05 ---
Chief complaint: sudden worst headache of life while exercising, onset 30 minutes prior. Associated with brief (90-second) left-hand paresthesia. BP 148/92. Neuro exam: transiently diminished proprioception in left hand, resolved during exam. CT head without contrast: no acute intracranial abnormality. Discharged with neurology urgent follow-up.

--- PROGRESS NOTE 2026-03-12 (Dr. Patel) ---
Patient seen urgently following ED visit 2026-03-05. New-onset "thunderclap" headache with transient focal neurologic deficit is a significant change from his established migraine pattern. Second similar episode 2026-03-09 with right-sided visual blur lasting 2 minutes. These are NEW red-flag features not previously present. CT head was reassuring but has limited sensitivity for posterior fossa lesions, small vascular malformations, and early ischemia. MRI brain with and without contrast is clinically indicated to evaluate: (1) posterior fossa mass, (2) arteriovenous malformation, (3) small vessel ischemic change, (4) pituitary lesion.

--- PROGRESS NOTE 2026-03-22 (Dr. Patel) ---
Third episode of transient focal symptoms (right-sided facial droop, 3 minutes) overnight 2026-03-20. Strong indication for MRI. Prior authorization request submitted.
""".strip(),
    payer_policy_title="IMG-HEAD-v7: Advanced Neuroimaging for Headache",
    payer_policy_text="""
Northstar Imaging Policy
Policy Number: IMG-HEAD-v7
Effective Date: October 1, 2025

SCOPE: MRI and MRA of the head/brain in the evaluation of headache disorders.

MEDICAL NECESSITY: Advanced neuroimaging is considered medically necessary when at least ONE of the following red-flag criteria is documented in the medical record:

(a) Sudden-onset severe ("thunderclap") headache reaching maximum intensity within one minute.

(b) New or progressive focal neurologic deficit (motor, sensory, visual, speech) associated with the headache.

(c) Significant change in headache pattern, frequency, or severity from the member's established baseline.

(d) Headache in an immunocompromised host or in the setting of active malignancy.

(e) Papilledema or other signs of increased intracranial pressure.

(f) Failure of adequate trial of first-line therapy (including at least two preventive agents for chronic migraine).

A prior negative non-contrast CT does NOT preclude MRI when red-flag features are present, as CT has limited sensitivity for posterior fossa lesions, small vascular malformations, and early ischemic change.
""".strip(),
    expected_appeal={
        "key_claims": [
            "Patient exhibits red-flag (a): thunderclap headache 2026-03-05.",
            "Patient exhibits red-flag (b): transient focal neurologic deficits on three separate dates.",
            "Patient exhibits red-flag (c): significant change from established migraine pattern.",
            "Policy explicitly states a negative CT does not preclude MRI when red flags are present.",
        ],
        "must_cite_source_types": ["payer_policy", "patient_chart"],
    },
)

CASE_3 = FixtureCase(
    case_id="case_03_pt_extension",
    dir_name="case_03_pt_extension",
    denial_letter_title="Meridian Health - Physical Therapy Extension Denial",
    denial_letter_text="""
Date: April 5, 2026

Member: Maria S. Gonzalez
Member ID: MH-44219087
Date of Birth: August 22, 1967
Plan: Meridian Health Plus
Provider: River Physical Therapy, NPI 9988776655

Dear Ms. Gonzalez:

Your request for an additional 12 physical therapy visits for post-operative rotator cuff repair rehabilitation has been DENIED.

Reason for denial: Member has exhausted the standard benefit allowance of 20 visits per episode of care. Request does not meet criteria for extension per policy REHAB-PT-v5, which requires documentation of ongoing measurable functional progress.

Denial code: REHAB-MAX-01.

You have the right to appeal within 60 days.

Meridian Health Utilization Management
""".strip(),
    patient_chart_text="""
PATIENT CHART - Maria S. Gonzalez
DOB: 1967-08-22  |  MRN: 00734612
Surgeon: Dr. Jin Park, MD (Orthopedic Surgery)
PT: River Physical Therapy

--- PROCEDURE ---
2026-01-08: Arthroscopic repair of right rotator cuff (supraspinatus, full-thickness tear). Post-op protocol: 6 weeks sling, progressive PT thereafter.

--- PT INITIAL EVAL 2026-02-19 ---
R shoulder flexion: 65 deg active, 100 deg passive. Abduction: 55 deg active. External rotation: 15 deg. Pain at rest 4/10, with movement 7/10. DASH score: 72.
Goals: functional flexion 150 deg, abduction 140 deg, return to work (bookkeeper, requires reaching overhead for files) by week 16.

--- PT PROGRESS SUMMARY (visits 1-10, through 2026-03-15) ---
Flexion: 65 -> 105 deg active. Abduction: 55 -> 90 deg. ER: 15 -> 30 deg. Pain with activity: 7/10 -> 4/10. DASH: 72 -> 54. Consistent measurable gains each week.

--- PT PROGRESS SUMMARY (visits 11-20, through 2026-04-02) ---
Flexion: 105 -> 130 deg. Abduction: 90 -> 115 deg. ER: 30 -> 45 deg. Pain with activity: 4/10 -> 2/10. DASH: 54 -> 38. Gains continue with each session.

--- SURGEON PROGRESS NOTE 2026-04-03 (Dr. Park) ---
Excellent post-op course. Continuing to demonstrate week-over-week functional gains. Not yet at full functional range (goal 150/140 flexion/abduction) but on track. Requires approximately 8-12 additional sessions to achieve work-readiness for her bookkeeping role (overhead reaching requirement). Discontinuing PT now would likely result in stiffness and need for manipulation under anesthesia.

--- PT PLAN OF CARE 2026-04-03 ---
Request 12 additional visits. Current objective goals: flexion 150, abduction 140, ER 60, DASH <= 20. Based on trajectory of prior 20 sessions, these goals are achievable within 8-12 sessions.
""".strip(),
    payer_policy_title="REHAB-PT-v5: Outpatient Physical Therapy Coverage",
    payer_policy_text="""
Meridian Health Medical Policy
Policy Number: REHAB-PT-v5
Effective Date: July 1, 2025

SCOPE: Outpatient physical therapy benefits.

STANDARD BENEFIT: 20 visits per episode of care.

EXTENSION CRITERIA: Additional visits (up to 20 more) may be approved when ALL of the following are documented:

1. Member has not yet achieved functional goals stated in the initial plan of care.

2. Documentation shows measurable functional improvement in at least two objective measures (range of motion, strength, functional outcome score such as DASH, Oswestry, LEFS, etc.) over the most recent four weeks.

3. Treating therapist and/or physician provide a written statement that additional visits are expected to result in further measurable improvement within a specific number of additional sessions.

4. Member's progress is not plateaued. A plateau is defined as no measurable improvement in objective metrics over four consecutive weeks.
""".strip(),
    expected_appeal={
        "key_claims": [
            "Patient has NOT yet met functional goals (flexion 130/150, abduction 115/140).",
            "Measurable improvement in four objective metrics in the last four weeks (flexion, abduction, ER, DASH).",
            "Surgeon and PT document specific goal-attainment estimate within 8-12 sessions.",
            "Progress is clearly ongoing, not plateaued.",
        ],
        "must_cite_source_types": ["payer_policy", "patient_chart"],
    },
)

CASE_4 = FixtureCase(
    case_id="case_04_cgm_t2dm_insulin",
    dir_name="case_04_cgm_t2dm_insulin",
    denial_letter_title="Summit Care - Durable Medical Equipment Denial",
    denial_letter_text="""
Date: April 7, 2026

Member: David T. Harrison
Member ID: SC-22019445
Date of Birth: February 11, 1961
Plan: Summit Care Select

Dear Mr. Harrison:

Your request for a continuous glucose monitoring (CGM) system (HCPCS A9276/A9277/A9278) has been DENIED.

Reason for denial: Per policy DME-CGM-v4, CGM is covered for members with Type 1 diabetes mellitus. Member's diagnosis is Type 2 diabetes. Denial code: DME-DX-02.

You have the right to appeal within 60 days.

Summit Care Plan Administration
""".strip(),
    patient_chart_text="""
PATIENT CHART - David T. Harrison
DOB: 1961-02-11  |  MRN: 00518244
Endocrinologist: Dr. Elena Vasquez, MD

--- DIAGNOSES ---
Type 2 diabetes mellitus with poor long-term control (E11.65), diagnosed 2009.

--- CURRENT INSULIN REGIMEN ---
Insulin glargine (Lantus) 38 units subcutaneous at bedtime
Insulin lispro (Humalog) 8-12 units subcutaneous with each meal (3x daily)
Total daily injections: 4

--- RECENT A1C ---
2025-04: 9.1%
2025-07: 8.7%
2025-10: 8.8%
2026-01: 9.0%
2026-04: 9.2%

--- HYPOGLYCEMIA HISTORY ---
2025-08-12: Hypoglycemic event requiring glucagon at home, fingerstick 42 mg/dL, symptoms of confusion and diaphoresis.
2025-11-03: Emergency department visit for severe hypoglycemia, fingerstick 38 mg/dL.
2026-02-18: Hypoglycemia while driving, fingerstick 46 mg/dL, self-treated with glucose tabs. No accident.

--- PROGRESS NOTE 2026-04-06 (Dr. Vasquez) ---
Patient has been on multiple daily insulin injections (MDI) for 14 years. Despite good adherence with SMBG 4-6 times per day, A1c has risen to 9.2% with three documented moderate-severe hypoglycemic episodes in the past 9 months. Recommending CGM to: (1) detect asymptomatic nocturnal and post-prandial hypoglycemia, (2) guide titration of multi-dose insulin, (3) reduce A1c while reducing hypoglycemia risk. Submitted PA for CGM.
""".strip(),
    payer_policy_title="DME-CGM-v4: Continuous Glucose Monitoring Systems",
    payer_policy_text="""
Summit Care Medical Policy
Policy Number: DME-CGM-v4
Effective Date: January 1, 2026

SCOPE: Coverage of continuous glucose monitoring (CGM) systems.

MEDICAL NECESSITY CRITERIA. CGM is considered medically necessary when the member meets at least ONE of the following:

1. Diagnosis of Type 1 diabetes mellitus.

2. Diagnosis of Type 2 diabetes mellitus AND ALL of the following:
   (a) Treated with three or more insulin injections per day OR with an insulin pump;
   (b) Requires frequent self-monitoring of blood glucose (four or more fingerstick tests per day);
   (c) Meets at least one of the following: (i) A1c greater than or equal to 8.0%; (ii) documented history of one or more episodes of severe or problematic hypoglycemia; (iii) hypoglycemia unawareness.

3. Pregnant with any form of diabetes mellitus requiring insulin.

NOTE: CGM policy was expanded in version 4 to include insulin-intensive Type 2 diabetes. Earlier denials that referenced Type 1 requirement only are no longer consistent with current policy.
""".strip(),
    expected_appeal={
        "key_claims": [
            "Patient has T2DM treated with 4 insulin injections per day (meets 2a).",
            "Patient performs 4-6 fingerstick glucose tests per day (meets 2b).",
            "Patient's A1c is 9.2%, above the 8.0% threshold (meets 2c-i).",
            "Patient has documented history of multiple severe hypoglycemia episodes (meets 2c-ii).",
            "Policy v4 explicitly covers insulin-intensive T2DM; denial cited outdated criteria.",
        ],
        "must_cite_source_types": ["payer_policy", "patient_chart"],
    },
)

CASE_5 = FixtureCase(
    case_id="case_05_adalimumab_ra",
    dir_name="case_05_adalimumab_ra",
    denial_letter_title="Evercare Plan - Specialty Pharmacy Denial",
    denial_letter_text="""
Date: April 10, 2026

Member: Sarah M. O'Brien
Member ID: EV-55930741
Date of Birth: June 30, 1979
Plan: Evercare Silver HMO
Ordering Physician: Dr. Amanda Cole, MD (Rheumatology)

Dear Ms. O'Brien:

Your request for adalimumab (Humira) 40mg subcutaneous every other week has been DENIED.

Reason for denial: Step-therapy requirement not satisfied. Per policy RX-BIO-RA-v6, biologic DMARDs for rheumatoid arthritis require documented inadequate response or intolerance to at least one conventional DMARD (methotrexate preferred) at an adequate trial duration. Denial code: STEP-02.

You have the right to appeal.

Evercare Plan Pharmacy Benefits
""".strip(),
    patient_chart_text="""
PATIENT CHART - Sarah M. O'Brien
DOB: 1979-06-30  |  MRN: 00628190
Rheumatologist: Dr. Amanda Cole, MD

--- DIAGNOSES ---
Rheumatoid arthritis, seropositive, moderate-to-severe activity (M05.79)
Diagnosed 2024-08. CCP antibody 312 U/mL. RF 89 IU/mL. Erosive changes on hand X-ray at diagnosis.

--- DMARD HISTORY ---
2024-08 to 2024-11: Hydroxychloroquine 400mg daily. Discontinued due to inadequate response (DAS28 remained >5.1 after 12 weeks).

2024-11 to 2025-10: Methotrexate. Started 10mg weekly, titrated to 25mg weekly (maximum tolerated) by 2025-02. Folate supplementation. 11 months of adequate-dose methotrexate. DAS28 at 2025-10: 4.9 (moderate disease activity, not remission). Hepatic enzymes progressively elevated: ALT rose from 24 to 96 U/L by 2025-09 (>3x upper limit of normal).

2025-10: Methotrexate held due to hepatotoxicity. Discussed with hepatology; advised against resumption due to persistent elevation.

2025-11 to 2026-03: Leflunomide 20mg daily as third DMARD trial. 20 weeks of treatment. DAS28 at 2026-03: 4.7 (moderate activity persists). Patient reports new hair thinning, GI upset.

--- CURRENT STATUS (2026-04-05, Dr. Cole) ---
Patient has failed/been intolerant to three conventional DMARDs: hydroxychloroquine (inadequate response), methotrexate (hepatotoxicity), leflunomide (inadequate response with side effects). Active erosive disease. Initiating biologic DMARD. Adalimumab selected due to moderate-severe activity and patient factors. Submitted PA.
""".strip(),
    payer_policy_title="RX-BIO-RA-v6: Biologic DMARDs for Rheumatoid Arthritis",
    payer_policy_text="""
Evercare Plan Medical Policy
Policy Number: RX-BIO-RA-v6
Effective Date: January 1, 2026

SCOPE: Biologic disease-modifying antirheumatic drugs (DMARDs) for rheumatoid arthritis.

MEDICAL NECESSITY CRITERIA. All of the following must be met:

1. Confirmed diagnosis of rheumatoid arthritis documented by a rheumatologist.

2. Moderate or severe disease activity (DAS28 at or above 3.2, or equivalent measure).

3. Step therapy: documented trial of at least one conventional DMARD at adequate dose and duration (generally 12 weeks), OR documented intolerance or contraindication to conventional DMARDs. Methotrexate is the preferred first-line agent; an inadequate response to methotrexate 15-25mg weekly for at least 12 weeks satisfies the step requirement. Intolerance is defined as a clinically significant adverse event requiring discontinuation (e.g., hepatotoxicity, cytopenia, persistent GI intolerance).

4. No active serious infection, no latent tuberculosis untreated, no active malignancy.
""".strip(),
    expected_appeal={
        "key_claims": [
            "Diagnosis confirmed by rheumatologist (Dr. Cole).",
            "Disease activity moderate (DAS28 4.7-4.9 across multiple assessments).",
            "Methotrexate trial of 11 months at maximum tolerated dose (25mg weekly) - exceeds 12-week requirement.",
            "Documented hepatotoxicity on methotrexate (ALT >3x ULN) is a clinically significant adverse event requiring discontinuation - meets intolerance definition.",
            "Additional failures of hydroxychloroquine and leflunomide further support biologic necessity.",
        ],
        "must_cite_source_types": ["payer_policy", "patient_chart"],
    },
)

ALL_CASES: list[FixtureCase] = [CASE_1, CASE_2, CASE_3, CASE_4, CASE_5]


def generate_all(root: Path = FIXTURES_ROOT) -> list[Path]:
    """Write all five cases to disk. Returns the list of case directories."""
    root.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for case in ALL_CASES:
        case_dir = root / case.dir_name
        case_dir.mkdir(parents=True, exist_ok=True)

        _write_pdf(
            case.denial_letter_title,
            case.denial_letter_text,
            case_dir / "denial_letter.pdf",
        )
        _write_pdf(
            case.payer_policy_title,
            case.payer_policy_text,
            case_dir / "payer_policy.pdf",
        )
        (case_dir / "patient_chart.txt").write_text(
            case.patient_chart_text + "\n", encoding="utf-8"
        )
        (case_dir / "expected.json").write_text(
            json.dumps(
                {
                    "case_id": case.case_id,
                    "expected_appeal": case.expected_appeal,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        created.append(case_dir)
    return created


if __name__ == "__main__":
    created = generate_all()
    for d in created:
        print(f"wrote {d.relative_to(FIXTURES_ROOT.parent)}")
    print(f"\n{len(created)} fixture case(s) generated.")
