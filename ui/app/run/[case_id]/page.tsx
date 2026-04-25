"use client";

import {
  use,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Link from "next/link";
import {
  type AppealDraft,
  type AppealReview,
  type CitationMarker,
  type ProgressEvent,
  type SourceType,
  type VerifiedAppeal,
  PIPELINE_STAGES,
  STAGE_DESCRIPTIONS,
  STAGE_LABELS,
  caseMeta,
} from "@/lib/types";

type StageState = {
  status: "pending" | "running" | "done" | "error";
  detail?: string;
};

type SourceKind = "denial_letter" | "patient_chart" | "payer_policy";

const SOURCE_LABELS: Record<SourceKind, string> = {
  denial_letter: "Denial letter",
  patient_chart: "Patient chart",
  payer_policy: "Payer policy",
};

function sourceKindFromType(t: SourceType): SourceKind | null {
  if (t === "denial_letter" || t === "patient_chart" || t === "payer_policy") {
    return t;
  }
  return null;
}

export default function RunPage({
  params,
}: {
  params: Promise<{ case_id: string }>;
}) {
  const { case_id: caseId } = use(params);
  const meta = caseMeta(caseId);

  const [stages, setStages] = useState<Record<string, StageState>>(() =>
    Object.fromEntries(
      PIPELINE_STAGES.map((s) => [s, { status: "pending" as const }])
    )
  );
  const [result, setResult] = useState<VerifiedAppeal | null>(null);
  const [editedDraft, setEditedDraft] = useState<AppealDraft | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // When the pipeline finishes, seed the editable draft once.
  useEffect(() => {
    if (result && !editedDraft) {
      setEditedDraft(structuredClone(result.draft));
    }
  }, [result, editedDraft]);

  const isEdited = useMemo(() => {
    if (!result || !editedDraft) return false;
    return JSON.stringify(result.draft) !== JSON.stringify(editedDraft);
  }, [result, editedDraft]);

  const downloadPdf = useCallback(async () => {
    if (!editedDraft) return;
    setDownloading(true);
    try {
      const res = await fetch("/api/export_pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(editedDraft),
      });
      if (!res.ok) {
        setError(`PDF export failed (${res.status})`);
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${editedDraft.case_id}_appeal.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } finally {
      setDownloading(false);
    }
  }, [editedDraft]);

  const resetEdits = useCallback(() => {
    if (result) setEditedDraft(structuredClone(result.draft));
  }, [result]);

  const [sources, setSources] = useState<Record<SourceKind, string>>({
    denial_letter: "",
    patient_chart: "",
    payer_policy: "",
  });
  const [activeTab, setActiveTab] = useState<SourceKind>("denial_letter");
  const [activeQuote, setActiveQuote] = useState<string | null>(null);
  const highlightRef = useRef<HTMLSpanElement | null>(null);

  // Fetch the three source documents once, so we can show them in the left pane
  // and highlight quotes when citations are clicked.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const kinds: SourceKind[] = [
        "denial_letter",
        "patient_chart",
        "payer_policy",
      ];
      const fetched = await Promise.all(
        kinds.map(async (k) => {
          try {
            const res = await fetch(`/api/case/${caseId}/source/${k}`);
            if (!res.ok) return [k, ""] as const;
            const data = (await res.json()) as { text: string };
            return [k, data.text] as const;
          } catch {
            return [k, ""] as const;
          }
        })
      );
      if (!cancelled) {
        setSources(
          Object.fromEntries(fetched) as Record<SourceKind, string>
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [caseId]);

  // Kick off the pipeline exactly once per case_id. With React Strict
  // Mode disabled in next.config.ts, a plain useEffect opens exactly
  // one EventSource per mount — no setTimeout-deferral trick needed,
  // no risk of a double pipeline run on initial render.
  useEffect(() => {
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
          setStages((prev) => ({
            ...prev,
            [event.stage]: {
              status: event.status === "done" ? "done" : "running",
              detail:
                event.status === "done"
                  ? describeDoneStage(event)
                  : STAGE_DESCRIPTIONS[event.stage],
            },
          }));
        }
      } catch (e) {
        console.error("SSE parse error", e);
      }
    };
    es.onerror = () => {
      // EventSource fires onerror when the server closes the
      // connection cleanly after sending "done". Suppress the error
      // banner in that case (readyState === CLOSED means we already
      // handled completion in onmessage).
      if (es.readyState !== EventSource.CLOSED) {
        setError("Connection to backend lost.");
      }
      es.close();
    };

    return () => {
      es.close();
    };
  }, [caseId]);

  // When the active citation changes, scroll the source pane to the highlight.
  useLayoutEffect(() => {
    if (highlightRef.current) {
      highlightRef.current.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }
  }, [activeQuote, activeTab]);

  const onCitationClick = useCallback((cm: CitationMarker) => {
    const kind = sourceKindFromType(cm.source_type);
    if (!kind) return;
    setActiveTab(kind);
    setActiveQuote(cm.verbatim_quote);
  }, []);

  const verifiedKeys = useMemo(() => {
    if (!result) return new Set<string>();
    return new Set(
      result.verified_citations.map(
        (v) => `${v.citation.source_id}|${v.citation.verbatim_quote}`
      )
    );
  }, [result]);

  const readinessBadge = (() => {
    if (error) {
      return (
        <StatusPill tone="rejected">
          Pipeline error
        </StatusPill>
      );
    }
    if (!result) {
      return (
        <StatusPill tone="running" pulse>
          Pipeline running…
        </StatusPill>
      );
    }
    const total =
      result.verified_citations.length + result.rejected_citations.length;
    if (result.ready_to_send) {
      return (
        <StatusPill tone="verified">
          Ready to send · {result.verified_citations.length}/{total} citations
          verified
        </StatusPill>
      );
    }
    return (
      <StatusPill tone="rejected">
        Not ready · {result.rejected_citations.length} rejected
      </StatusPill>
    );
  })();

  return (
    <>
      {/* Patient identifier strip */}
      <div className="border-b border-border bg-card">
        <div className="mx-auto max-w-[1600px] px-6 py-3">
          <Link
            href="/"
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            ← worklist
          </Link>
          <div className="mt-1 flex flex-wrap items-baseline gap-x-8 gap-y-1 text-sm">
            <IdField label="Patient" value={meta?.patient_name ?? caseId} bold />
            <IdField label="DOB" value={meta?.date_of_birth ?? "—"} mono />
            <IdField label="Member" value={meta?.member_id ?? "—"} mono />
            <IdField label="Plan" value={meta?.plan ?? "—"} />
            <IdField
              label="Service denied"
              value={meta?.service ?? "—"}
            />
            <IdField
              label="Denial date"
              value={meta?.denial_date ?? "—"}
              mono
            />
            <div className="ml-auto">{readinessBadge}</div>
          </div>
        </div>
        <PipelineStepper stages={stages} />
      </div>

      {/* Two-pane review */}
      <main className="flex min-h-0 flex-1">
        <div className="mx-auto grid w-full max-w-[1600px] min-h-0 flex-1 grid-cols-2 divide-x divide-border">
          {/* Left: source documents */}
          <section className="flex min-h-0 flex-col">
            <div className="flex border-b border-border bg-card">
              {(Object.keys(SOURCE_LABELS) as SourceKind[]).map((k) => (
                <button
                  key={k}
                  onClick={() => setActiveTab(k)}
                  className={
                    "px-4 py-2 text-xs font-medium transition-colors " +
                    (activeTab === k
                      ? "border-b-2 border-primary text-foreground"
                      : "border-b-2 border-transparent text-muted-foreground hover:text-foreground")
                  }
                >
                  {SOURCE_LABELS[k]}
                </button>
              ))}
              {activeQuote && (
                <button
                  onClick={() => setActiveQuote(null)}
                  className="ml-auto mr-2 self-center text-xs text-muted-foreground hover:text-foreground"
                >
                  clear highlight
                </button>
              )}
            </div>
            <div className="flex-1 min-h-0 overflow-auto bg-card px-6 py-4">
              {sources[activeTab] ? (
                <HighlightedText
                  text={sources[activeTab]}
                  highlight={activeQuote}
                  highlightRef={highlightRef}
                />
              ) : (
                <div className="text-sm text-muted-foreground">
                  Loading {SOURCE_LABELS[activeTab].toLowerCase()}…
                </div>
              )}
            </div>
          </section>

          {/* Right: appeal draft */}
          <section className="flex min-h-0 flex-col bg-[color:color-mix(in_oklch,var(--background),var(--muted)_35%)]">
            <div className="flex-1 min-h-0 overflow-auto px-8 py-8">
              <div className="mx-auto flex max-w-[680px] flex-col gap-6">
                {result && editedDraft ? (
                  <>
                    <LetterToolbar
                      isEdited={isEdited}
                      downloading={downloading}
                      onDownload={downloadPdf}
                      onReset={resetEdits}
                    />
                    <EditableLetter
                      draft={editedDraft}
                      onDraftChange={setEditedDraft}
                      verifiedKeys={verifiedKeys}
                      onCitationClick={onCitationClick}
                      rejected={result.rejected_citations}
                    />
                    {result.second_pass_review && (
                      <SecondPassReview review={result.second_pass_review} />
                    )}
                  </>
                ) : (
                  <DraftSkeleton stages={stages} error={error} />
                )}
              </div>
            </div>
          </section>
        </div>
      </main>
    </>
  );
}

function IdField({
  label,
  value,
  bold,
  mono,
}: {
  label: string;
  value: string;
  bold?: boolean;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <span
        className={
          (bold ? "font-semibold " : "") +
          (mono ? "tabular-nums font-mono text-xs " : "") +
          "text-foreground"
        }
      >
        {value}
      </span>
    </div>
  );
}

function StatusPill({
  children,
  tone,
  pulse,
}: {
  children: React.ReactNode;
  tone: "verified" | "rejected" | "running";
  pulse?: boolean;
}) {
  const toneClass =
    tone === "verified"
      ? "bg-[--color-status-verified-bg] text-[--color-status-verified]"
      : tone === "rejected"
        ? "bg-[--color-status-rejected-bg] text-[--color-status-rejected]"
        : "bg-[--color-status-running-bg] text-[--color-status-running]";
  const dotClass =
    tone === "verified"
      ? "bg-[--color-status-verified]"
      : tone === "rejected"
        ? "bg-[--color-status-rejected]"
        : "bg-[--color-status-running]";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-sm px-2 py-0.5 text-xs font-medium ${toneClass}`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${dotClass} ${pulse ? "animate-pulse" : ""}`}
      />
      {children}
    </span>
  );
}

function PipelineStepper({
  stages,
}: {
  stages: Record<string, StageState>;
}) {
  return (
    <div className="border-t border-border bg-muted/30">
      <ol className="mx-auto flex max-w-[1600px] items-stretch">
        {PIPELINE_STAGES.map((s, i) => {
          const st = stages[s];
          const dotClass =
            st.status === "done"
              ? "bg-[--color-status-verified]"
              : st.status === "running"
                ? "bg-[--color-status-running] animate-pulse ring-2 ring-[--color-status-running]/30"
                : st.status === "error"
                  ? "bg-[--color-status-rejected]"
                  : "bg-muted-foreground/30";
          const textClass =
            st.status === "pending"
              ? "text-muted-foreground/60"
              : "text-foreground";
          return (
            <li
              key={s}
              className="flex-1 border-r border-border last:border-r-0 px-4 py-2"
            >
              <div className="flex items-center gap-2">
                <span
                  className={`h-2 w-2 rounded-full ${dotClass} shrink-0`}
                />
                <span
                  className={`text-[11px] uppercase tracking-wider ${textClass}`}
                >
                  {String(i + 1).padStart(2, "0")} · {STAGE_LABELS[s]}
                </span>
              </div>
              <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
                {st.detail ?? "—"}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function HighlightedText({
  text,
  highlight,
  highlightRef,
}: {
  text: string;
  highlight: string | null;
  highlightRef: React.RefObject<HTMLSpanElement | null>;
}) {
  const parts = useMemo(() => findSpan(text, highlight), [text, highlight]);
  if (!parts) {
    return (
      <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-foreground">
        {text}
      </pre>
    );
  }
  const [before, match, after] = parts;
  return (
    <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-foreground">
      {before}
      <span ref={highlightRef} className="source-highlight">
        {match}
      </span>
      {after}
    </pre>
  );
}

function findSpan(
  text: string,
  quote: string | null
): [string, string, string] | null {
  if (!quote || !text) return null;
  const idx = text.indexOf(quote);
  if (idx !== -1) {
    return [text.slice(0, idx), text.slice(idx, idx + quote.length), text.slice(idx + quote.length)];
  }
  // Fallback: whitespace-flexible, case-insensitive regex match.
  try {
    const trimmed = quote.trim();
    if (!trimmed) return null;
    const pat = trimmed
      .replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
      .replace(/\s+/g, "\\s+");
    const re = new RegExp(pat, "i");
    const m = re.exec(text);
    if (!m) return null;
    return [
      text.slice(0, m.index),
      text.slice(m.index, m.index + m[0].length),
      text.slice(m.index + m[0].length),
    ];
  } catch {
    return null;
  }
}

function LetterToolbar({
  isEdited,
  downloading,
  onDownload,
  onReset,
}: {
  isEdited: boolean;
  downloading: boolean;
  onDownload: () => void;
  onReset: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-sm border border-border bg-card px-3 py-2">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        {isEdited ? (
          <span className="inline-flex items-center gap-1.5 rounded-sm bg-amber-500/10 px-2 py-0.5 text-amber-700">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
            edited locally
          </span>
        ) : (
          <span>Edit any paragraph in place — changes live in your browser only.</span>
        )}
      </div>
      <div className="flex items-center gap-2">
        {isEdited && (
          <button
            onClick={onReset}
            className="rounded-sm border border-border px-3 py-1 text-xs font-medium hover:bg-muted"
          >
            Reset
          </button>
        )}
        <button
          onClick={onDownload}
          disabled={downloading}
          className="inline-flex items-center gap-1.5 rounded-sm border border-primary bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {downloading ? "Generating…" : "Download PDF"}
        </button>
      </div>
    </div>
  );
}

function EditableLetter({
  draft,
  onDraftChange,
  verifiedKeys,
  onCitationClick,
  rejected,
}: {
  draft: AppealDraft;
  onDraftChange: (d: AppealDraft) => void;
  verifiedKeys: Set<string>;
  onCitationClick: (c: CitationMarker) => void;
  rejected: VerifiedAppeal["rejected_citations"];
}) {
  const updateField = (
    field: "subject_line" | "recipient_plan",
    value: string
  ) => {
    onDraftChange({ ...draft, [field]: value });
  };

  const updateParagraph = (
    idx: number,
    field: "heading" | "text",
    value: string
  ) => {
    onDraftChange({
      ...draft,
      paragraphs: draft.paragraphs.map((p, i) =>
        i === idx ? { ...p, [field]: value } : p
      ),
    });
  };

  return (
    <article className="rounded-sm border border-border bg-card p-10 shadow-sm">
      <header className="mb-6 border-b border-border pb-4">
        <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
          Appeal of prior authorization denial
        </div>
        <input
          type="text"
          value={draft.subject_line}
          onChange={(e) => updateField("subject_line", e.target.value)}
          className="mt-1 w-full bg-transparent text-lg font-semibold leading-snug tracking-tight outline-none focus:ring-1 focus:ring-primary/40 rounded-sm px-1 -mx-1"
        />
        <div className="mt-2 text-sm text-muted-foreground">
          To:{" "}
          <input
            type="text"
            value={draft.recipient_plan}
            onChange={(e) => updateField("recipient_plan", e.target.value)}
            className="w-[80%] bg-transparent text-foreground outline-none focus:ring-1 focus:ring-primary/40 rounded-sm px-1 -mx-1"
          />
        </div>
      </header>

      <div className="letter-body flex flex-col gap-5 text-[15px] leading-relaxed">
        {draft.paragraphs.map((p, i) => (
          <section key={i} className="flex flex-col gap-2">
            {p.heading !== null && p.heading !== undefined && (
              <input
                type="text"
                value={p.heading}
                onChange={(e) => updateParagraph(i, "heading", e.target.value)}
                className="font-serif text-sm font-semibold uppercase tracking-wider text-muted-foreground bg-transparent outline-none focus:ring-1 focus:ring-primary/40 rounded-sm px-1 -mx-1"
              />
            )}
            <textarea
              value={p.text}
              onChange={(e) => updateParagraph(i, "text", e.target.value)}
              rows={Math.max(3, p.text.split("\n").length + Math.ceil(p.text.length / 90))}
              className="w-full bg-transparent text-foreground whitespace-pre-wrap resize-none outline-none focus:ring-1 focus:ring-primary/40 rounded-sm px-1 -mx-1 font-serif"
              style={{ fieldSizing: "content" } as React.CSSProperties}
            />
            {p.citations.length > 0 && (
              <div className="flex flex-wrap gap-1.5 pt-1 font-sans">
                {p.citations.map((c, j) => {
                  const verified = verifiedKeys.has(
                    `${c.source_id}|${c.verbatim_quote}`
                  );
                  return (
                    <CitationChip
                      key={j}
                      citation={c}
                      verified={verified}
                      onClick={() => onCitationClick(c)}
                    />
                  );
                })}
              </div>
            )}
          </section>
        ))}
      </div>

      {rejected.length > 0 && (
        <aside className="mt-8 rounded-sm border border-[--color-status-rejected]/30 bg-[--color-status-rejected-bg] p-4">
          <div className="text-xs font-semibold uppercase tracking-wider text-[--color-status-rejected]">
            Verifier stripped {rejected.length} citation(s)
          </div>
          <ul className="mt-2 flex flex-col gap-2 text-xs">
            {rejected.map((r, i) => (
              <li key={i} className="flex flex-col gap-0.5">
                <span className="font-mono text-[11px] text-[--color-status-rejected]">
                  {r.citation.source_id}
                </span>
                <span className="text-foreground">{r.citation.claim}</span>
                <span className="italic text-muted-foreground">
                  {r.rejection_reason}
                </span>
              </li>
            ))}
          </ul>
        </aside>
      )}
    </article>
  );
}

function CitationChip({
  citation,
  verified,
  onClick,
}: {
  citation: CitationMarker;
  verified: boolean;
  onClick: () => void;
}) {
  const sourceLabel =
    citation.source_type === "denial_letter"
      ? "denial"
      : citation.source_type === "patient_chart"
        ? "chart"
        : citation.source_type === "payer_policy"
          ? "policy"
          : citation.source_type;
  return (
    <button
      onClick={onClick}
      title={citation.verbatim_quote}
      className={
        "inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-[11px] font-mono transition-colors cursor-pointer " +
        (verified
          ? "border-[--color-status-verified]/30 bg-[--color-status-verified-bg] text-[--color-status-verified] hover:bg-[--color-status-verified-bg]/80"
          : "border-[--color-status-rejected]/30 bg-[--color-status-rejected-bg] text-[--color-status-rejected] hover:bg-[--color-status-rejected-bg]/80")
      }
    >
      <span className="opacity-60">{verified ? "✓" : "✗"}</span>
      <span>
        {sourceLabel}·{citation.source_id.split("_q")[1] ?? citation.source_id}
      </span>
    </button>
  );
}

function DraftSkeleton({
  stages,
  error,
}: {
  stages: Record<string, StageState>;
  error: string | null;
}) {
  const stageInProgress = PIPELINE_STAGES.find(
    (s) => stages[s].status === "running"
  );
  const completed = PIPELINE_STAGES.filter(
    (s) => stages[s].status === "done"
  ).length;

  if (error) {
    return (
      <div className="rounded-sm border border-[--color-status-rejected]/30 bg-[--color-status-rejected-bg] p-6">
        <div className="text-sm font-medium text-[--color-status-rejected]">
          Pipeline error
        </div>
        <div className="mt-1 text-sm text-foreground">{error}</div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 rounded-sm border border-dashed border-border bg-card/60 p-10">
      <div className="text-sm text-muted-foreground">
        {stageInProgress
          ? STAGE_DESCRIPTIONS[stageInProgress] ?? "Running…"
          : "Starting pipeline…"}
      </div>
      <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
        <div
          className="h-full bg-[--color-status-running] transition-all"
          style={{ width: `${(completed / PIPELINE_STAGES.length) * 100}%` }}
        />
      </div>
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
        {completed} of {PIPELINE_STAGES.length} stages complete
      </div>
    </div>
  );
}

function describeDoneStage(event: ProgressEvent): string {
  switch (event.stage) {
    case "denial_analyzer":
      return `${event.source_quotes ?? "?"} source quotes · ${event.denial_reasons ?? "?"} denial reasons`;
    case "policy_reader":
      return `${event.criteria ?? "?"} medical-necessity criteria extracted`;
    case "chart_miner":
      return `${event.evidence_items ?? "?"} evidence items found in chart`;
    case "guideline_citer":
      return `${event.citations ?? "?"} clinical guidelines cited`;
    case "letter_writer":
      return `${event.paragraphs ?? "?"} paragraphs · ${event.citations ?? "?"} citations drafted`;
    case "verifier": {
      const v = (event.verified_citations as number) ?? 0;
      const r = (event.rejected_citations as number) ?? 0;
      return `${v}/${v + r} citations verified`;
    }
    case "independent_reviewer": {
      const verdict = (event.overall_verdict as string) ?? "?";
      const concerns = (event.high_level_concerns as number) ?? 0;
      return `${verdict.replace("_", " ")} · ${concerns} concern(s) flagged`;
    }
    default:
      return "Done.";
  }
}

function SecondPassReview({ review }: { review: AppealReview }) {
  const ready = review.overall_verdict === "sign_ready";
  const verdictCounts = review.citation_verdicts.reduce<Record<string, number>>(
    (acc, v) => {
      acc[v.verdict] = (acc[v.verdict] ?? 0) + 1;
      return acc;
    },
    {}
  );

  return (
    <article className="rounded-sm border border-border bg-card p-6">
      <header className="mb-4 flex items-baseline justify-between gap-4 border-b border-border pb-3">
        <div className="flex flex-col gap-1">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Independent second-pass review
          </div>
          <h2 className="text-base font-semibold">
            Reviewer assessment
          </h2>
        </div>
        <span
          className={
            "inline-flex items-center gap-1.5 rounded-sm px-2 py-0.5 text-xs font-medium " +
            (ready
              ? "bg-[--color-status-verified-bg] text-[--color-status-verified]"
              : "bg-[--color-status-rejected-bg] text-[--color-status-rejected]")
          }
        >
          <span
            className={
              "h-1.5 w-1.5 rounded-full " +
              (ready
                ? "bg-[--color-status-verified]"
                : "bg-[--color-status-rejected]")
            }
          />
          {ready ? "Sign-ready" : "Needs revision"}
        </span>
      </header>

      <p className="text-sm leading-relaxed text-foreground">
        {review.reviewer_summary}
      </p>

      {review.high_level_concerns.length > 0 && (
        <div className="mt-4">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Concerns to address before signing
          </div>
          <ul className="mt-2 flex flex-col gap-1 text-sm">
            {review.high_level_concerns.map((c, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-[--color-status-rejected]">•</span>
                <span>{c}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-4">
        <div className="flex items-baseline justify-between text-[11px] uppercase tracking-wider text-muted-foreground">
          <span>Per-citation verdicts</span>
          <span className="tabular-nums">
            {Object.entries(verdictCounts)
              .map(([k, n]) => `${n} ${k}`)
              .join(" · ")}
          </span>
        </div>
        <ul className="mt-2 flex flex-col gap-1.5">
          {review.citation_verdicts.map((v, i) => (
            <li
              key={i}
              className="flex items-start gap-2 rounded-sm border border-border px-2 py-1.5 text-xs"
            >
              <VerdictDot verdict={v.verdict} />
              <div className="flex flex-1 flex-col">
                <span className="font-mono text-[11px] text-muted-foreground">
                  paragraph {v.paragraph_index} · citation{" "}
                  {v.citation_in_paragraph_index} · {v.source_id}
                </span>
                <span className="text-foreground">{v.rationale}</span>
              </div>
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
                {v.verdict}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </article>
  );
}

function VerdictDot({
  verdict,
}: {
  verdict: "supports" | "partial" | "unsupported";
}) {
  const cls =
    verdict === "supports"
      ? "bg-[--color-status-verified]"
      : verdict === "partial"
        ? "bg-amber-500"
        : "bg-[--color-status-rejected]";
  return <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${cls}`} />;
}
