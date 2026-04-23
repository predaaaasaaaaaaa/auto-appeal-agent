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

export type VerifiedAppeal = {
  case_id: string;
  draft: AppealDraft;
  verified_citations: VerifiedCitation[];
  rejected_citations: RejectedCitation[];
  verification_pass_rate: number;
  ready_to_send: boolean;
};

export type CaseSummary = {
  case_id: string;
  expected_appeal?: {
    key_claims?: string[];
    must_cite_source_types?: string[];
  };
};

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

// Human-readable labels for each stage.
export const STAGE_LABELS: Record<string, string> = {
  denial_analyzer: "Denial Analyzer",
  policy_reader: "Policy Reader",
  chart_miner: "Chart Miner",
  guideline_citer: "Guideline Citer",
  letter_writer: "Letter Writer",
  verifier: "Verifier",
};

// Short descriptions shown while a stage runs.
export const STAGE_DESCRIPTIONS: Record<string, string> = {
  denial_analyzer: "Reading denial letter with high-res vision...",
  policy_reader: "Extracting medical-necessity criteria from payer policy...",
  chart_miner: "Finding evidence in patient chart...",
  guideline_citer: "Looking up supporting clinical guidelines...",
  letter_writer: "Drafting appeal letter with citations...",
  verifier: "Re-checking every citation against its source...",
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
