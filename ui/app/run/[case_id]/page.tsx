"use client";

import { use, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  type ProgressEvent,
  type VerifiedAppeal,
  type CitationMarker,
  PIPELINE_STAGES,
  STAGE_DESCRIPTIONS,
  STAGE_LABELS,
  humanCaseId,
} from "@/lib/types";

type StageState = {
  status: "pending" | "running" | "done" | "error";
  detail?: string;
};

function sourceTypeLabel(t: string): string {
  switch (t) {
    case "denial_letter":
      return "Denial letter";
    case "patient_chart":
      return "Patient chart";
    case "payer_policy":
      return "Payer policy";
    case "clinical_guideline":
      return "Guideline";
    default:
      return t;
  }
}

function CitationPill({
  citation,
  verified,
}: {
  citation: CitationMarker;
  verified: boolean;
}) {
  return (
    <span
      title={`${sourceTypeLabel(citation.source_type)} — "${citation.verbatim_quote}"`}
      className={
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-mono cursor-help " +
        (verified
          ? "border-emerald-600/30 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300"
          : "border-red-600/30 bg-red-500/10 text-red-800 dark:text-red-300")
      }
    >
      <span className="opacity-60">{verified ? "✓" : "✗"}</span>
      {citation.source_id}
    </span>
  );
}

export default function RunPage({
  params,
}: {
  params: Promise<{ case_id: string }>;
}) {
  const { case_id: caseId } = use(params);
  const [stages, setStages] = useState<Record<string, StageState>>(
    () =>
      Object.fromEntries(
        PIPELINE_STAGES.map((s) => [s, { status: "pending" as const }])
      )
  );
  const [result, setResult] = useState<VerifiedAppeal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    const es = new EventSource(`/api/run/${caseId}`);

    es.onmessage = (msg) => {
      try {
        const event = JSON.parse(msg.data) as ProgressEvent;

        if (event.stage === "done" && event.result) {
          setResult(event.result);
          es.close();
          return;
        }

        if (event.stage === "error") {
          setError(event.message ?? "Unknown error");
          es.close();
          return;
        }

        if (PIPELINE_STAGES.includes(event.stage)) {
          setStages((prev) => {
            const next = { ...prev };
            const status = event.status === "done" ? "done" : "running";
            const detail =
              event.status === "done"
                ? describeDoneStage(event)
                : STAGE_DESCRIPTIONS[event.stage];
            next[event.stage] = { status, detail };
            return next;
          });
        }
      } catch (err) {
        console.error("SSE parse error", err, msg.data);
      }
    };

    es.onerror = () => {
      setError("Connection to backend lost.");
      es.close();
    };

    return () => {
      es.close();
    };
  }, [caseId]);

  const stagesComplete = PIPELINE_STAGES.filter(
    (s) => stages[s].status === "done"
  ).length;
  const progressPct = (stagesComplete / PIPELINE_STAGES.length) * 100;

  const verifiedIds = useMemo(() => {
    if (!result) return new Set<string>();
    return new Set(
      result.verified_citations.map(
        (v) => `${v.citation.source_id}|${v.citation.verbatim_quote}`
      )
    );
  }, [result]);

  return (
    <main className="flex flex-1 justify-center px-6 py-12">
      <div className="w-full max-w-4xl flex flex-col gap-8">
        <div className="flex items-center justify-between">
          <div className="flex flex-col gap-1">
            <Link
              href="/"
              className="text-sm text-muted-foreground hover:text-foreground"
            >
              ← back
            </Link>
            <h1 className="text-2xl font-semibold tracking-tight">
              {humanCaseId(caseId)}
            </h1>
          </div>
          {result && (
            <div className="flex items-center gap-2">
              {result.ready_to_send ? (
                <Badge className="bg-emerald-600 hover:bg-emerald-600">
                  Ready to send
                </Badge>
              ) : (
                <Badge variant="destructive">Not ready</Badge>
              )}
              <span className="text-sm text-muted-foreground">
                {(result.verification_pass_rate * 100).toFixed(0)}% verified
              </span>
            </div>
          )}
        </div>

        {/* Pipeline progress */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Pipeline progress</CardTitle>
            <Progress value={progressPct} className="mt-2" />
          </CardHeader>
          <CardContent>
            <ol className="flex flex-col gap-2">
              {PIPELINE_STAGES.map((s) => {
                const st = stages[s];
                return (
                  <li
                    key={s}
                    className="flex items-start gap-3 rounded-md border p-3"
                  >
                    <StageIcon status={st.status} />
                    <div className="flex flex-col">
                      <span className="font-medium text-sm">
                        {STAGE_LABELS[s]}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {st.detail ?? "Waiting..."}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ol>
          </CardContent>
        </Card>

        {error && (
          <Card className="border-destructive/40">
            <CardHeader>
              <CardTitle className="text-base text-destructive">
                Pipeline error
              </CardTitle>
            </CardHeader>
            <CardContent className="text-sm">{error}</CardContent>
          </Card>
        )}

        {/* Appeal letter */}
        {result && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                {result.draft.subject_line}
              </CardTitle>
              <div className="text-sm text-muted-foreground pt-1">
                To: <span className="font-medium">{result.draft.recipient_plan}</span>
              </div>
            </CardHeader>
            <CardContent className="flex flex-col gap-6">
              {result.draft.paragraphs.map((p, i) => (
                <div key={i} className="flex flex-col gap-2">
                  {p.heading && (
                    <h3 className="font-semibold text-sm">{p.heading}</h3>
                  )}
                  <p className="text-sm leading-relaxed whitespace-pre-wrap">
                    {p.text}
                  </p>
                  {p.citations.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {p.citations.map((c, j) => (
                        <CitationPill
                          key={j}
                          citation={c}
                          verified={verifiedIds.has(
                            `${c.source_id}|${c.verbatim_quote}`
                          )}
                        />
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </CardContent>
          </Card>
        )}

        {/* Rejection summary */}
        {result && result.rejected_citations.length > 0 && (
          <Card className="border-red-500/40">
            <CardHeader>
              <CardTitle className="text-base">
                Rejected citations ({result.rejected_citations.length})
              </CardTitle>
              <span className="text-xs text-muted-foreground">
                These claims failed verification and were stripped from the
                letter.
              </span>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 text-sm">
              {result.rejected_citations.map((r, i) => (
                <div key={i} className="rounded border border-red-500/20 p-2">
                  <div className="font-mono text-xs text-red-700 dark:text-red-300">
                    {r.citation.source_id}
                  </div>
                  <div className="mt-1">{r.citation.claim}</div>
                  <div className="mt-1 italic text-muted-foreground">
                    {r.rejection_reason}
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        )}
      </div>
    </main>
  );
}

function describeDoneStage(event: ProgressEvent): string {
  switch (event.stage) {
    case "denial_analyzer":
      return `Captured ${event.source_quotes ?? "?"} source quote(s), ${event.denial_reasons ?? "?"} denial reason(s).`;
    case "policy_reader":
      return `Extracted ${event.criteria ?? "?"} medical-necessity criteria.`;
    case "chart_miner":
      return `Found ${event.evidence_items ?? "?"} matching evidence item(s).`;
    case "guideline_citer":
      return `Cited ${event.citations ?? "?"} clinical guideline(s).`;
    case "letter_writer":
      return `Drafted ${event.paragraphs ?? "?"} paragraph(s), ${event.citations ?? "?"} citation(s).`;
    case "verifier":
      return `Verified ${event.verified_citations ?? "?"} / ${
        (event.verified_citations as number ?? 0) +
        (event.rejected_citations as number ?? 0)
      } citations.`;
    default:
      return "Done.";
  }
}

function StageIcon({ status }: { status: StageState["status"] }) {
  const base = "mt-1 h-3 w-3 rounded-full shrink-0 ";
  if (status === "done") return <div className={base + "bg-emerald-500"} />;
  if (status === "running")
    return (
      <div
        className={base + "bg-blue-500 animate-pulse ring-2 ring-blue-500/30"}
      />
    );
  if (status === "error") return <div className={base + "bg-red-500"} />;
  return <div className={base + "bg-muted"} />;
}
