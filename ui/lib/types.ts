// Mirrors the Pydantic schemas in src/auto_appeal_agent/schemas.py.
// Kept intentionally minimal — only the fields the UI actually reads.

export type SourceType =
  | "denial_letter"
  | "patient_chart"
  | "payer_policy"
  | "clinical_guideline";

export type SourceQuote = {
  quote_id: string;
  source_type: SourceType;
  quote: string;
  location: string;
};

export type CitationMarker = {
  claim: string;
  source_type: SourceType;
  source_id: string;
  verbatim_quote: string;
};

export type AppealParagraph = {
  heading: string | null;
  text: string;
  citations: CitationMarker[];
};

export type AppealDraft = {
  case_id: string;
  recipient_plan: string;
  subject_line: string;
  paragraphs: AppealParagraph[];
};

export type VerifiedCitation = {
  citation: CitationMarker;
  verified: boolean;
  verification_method: string;
  notes: string;
};

export type RejectedCitation = {
  citation: CitationMarker;
  rejection_reason: string;
};

export type CitationVerdict = {
  paragraph_index: number;
  citation_in_paragraph_index: number;
  source_id: string;
  verdict: "supports" | "partial" | "unsupported";
  rationale: string;
};

export type AppealReview = {
  case_id: string;
  overall_verdict: "sign_ready" | "needs_revision";
  citation_verdicts: CitationVerdict[];
  high_level_concerns: string[];
  reviewer_summary: string;
};

export type VerifiedAppeal = {
  case_id: string;
  draft: AppealDraft;
  verified_citations: VerifiedCitation[];
  rejected_citations: RejectedCitation[];
  verification_pass_rate: number;
  ready_to_send: boolean;
  second_pass_review: AppealReview | null;
};

export type CaseSummary = {
  case_id: string;
  expected_appeal?: {
    key_claims?: string[];
    must_cite_source_types?: string[];
  };
};

// Display metadata that turns an opaque case_id into something a prior-auth
// specialist recognizes (patient, service, plan, date). Hardcoded here for
// the hackathon; in production this would live on the case record itself.
export type CaseMeta = {
  patient_name: string;
  date_of_birth: string;
  member_id: string;
  service: string;
  plan: string;
  denial_date: string;
  clinical_domain: string;
};

export const CASE_META: Record<string, CaseMeta> = {
  case_01_ozempic_bmi34: {
    patient_name: "Jane A. Doe",
    date_of_birth: "1978-05-14",
    member_id: "BS-A1234567",
    service: "Semaglutide (Ozempic) 1 mg weekly",
    plan: "BlueSun Health Premium HMO",
    denial_date: "2026-04-01",
    clinical_domain: "Endocrinology / Obesity medicine",
  },
  case_02_brain_mri_headache: {
    patient_name: "Robert K. Lee",
    date_of_birth: "1984-10-03",
    member_id: "NS-77881266",
    service: "MRI brain with and without contrast (CPT 70553)",
    plan: "Northstar Gold PPO",
    denial_date: "2026-03-28",
    clinical_domain: "Neurology / Advanced imaging",
  },
  case_03_pt_extension: {
    patient_name: "Maria S. Gonzalez",
    date_of_birth: "1967-08-22",
    member_id: "MH-44219087",
    service: "Physical therapy — 12 additional visits",
    plan: "Meridian Health Plus",
    denial_date: "2026-04-05",
    clinical_domain: "Orthopedics / Rehabilitation",
  },
  case_04_cgm_t2dm_insulin: {
    patient_name: "David T. Harrison",
    date_of_birth: "1961-02-11",
    member_id: "SC-22019445",
    service: "Continuous glucose monitor (HCPCS A9276/A9277/A9278)",
    plan: "Summit Care Select",
    denial_date: "2026-04-07",
    clinical_domain: "Endocrinology / Diabetes",
  },
  case_05_adalimumab_ra: {
    patient_name: "Sarah M. O'Brien",
    date_of_birth: "1979-06-30",
    member_id: "EV-55930741",
    service: "Adalimumab (Humira) 40 mg subcutaneous q2w",
    plan: "Evercare Silver HMO",
    denial_date: "2026-04-10",
    clinical_domain: "Rheumatology / Biologics",
  },
};

export function caseMeta(caseId: string): CaseMeta | null {
  return CASE_META[caseId] ?? null;
}

// The shape of SSE events emitted by /api/run/{case_id}.
// `stage` is the agent name ("denial_analyzer", etc.), "done", or "error".
export type ProgressEvent = {
  stage: string;
  status?: "running" | "done";
  result?: VerifiedAppeal;
  message?: string;
  error_type?: string;
  [key: string]: unknown;
};

export const PIPELINE_STAGES: readonly string[] = [
  "denial_analyzer",
  "policy_reader",
  "chart_miner",
  "guideline_citer",
  "letter_writer",
  "verifier",
] as const;
// Note: "independent_reviewer" is opt-in via second_pass=True and not
// part of the default stepper. Its label/description stay in the maps
// below so the run page can still display the review when present.

// Human-readable labels for each stage.
export const STAGE_LABELS: Record<string, string> = {
  denial_analyzer: "Denial Analyzer",
  policy_reader: "Policy Reader",
  chart_miner: "Chart Miner",
  guideline_citer: "Guideline Citer",
  letter_writer: "Letter Writer",
  verifier: "Verifier",
  independent_reviewer: "Independent Reviewer",
};

// Short descriptions shown while a stage runs.
export const STAGE_DESCRIPTIONS: Record<string, string> = {
  denial_analyzer: "Reading denial letter with high-res vision...",
  policy_reader: "Extracting medical-necessity criteria from payer policy...",
  chart_miner: "Finding evidence in patient chart...",
  guideline_citer: "Looking up supporting clinical guidelines...",
  letter_writer: "Drafting appeal letter with citations...",
  verifier: "Re-checking every citation against its source...",
  independent_reviewer:
    "Fresh-context second opinion: do citations actually support the claims?",
};

export function humanCaseId(caseId: string): string {
  // "case_01_ozempic_bmi34" → "Case 01 — Ozempic (BMI 34)"
  const parts = caseId.replace(/^case_/, "").split("_");
  if (parts.length < 2) return caseId;
  const [num, ...rest] = parts;
  const label = rest
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
  return `Case ${num} — ${label}`;
}
