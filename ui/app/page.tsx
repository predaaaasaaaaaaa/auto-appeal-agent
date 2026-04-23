import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { type CaseSummary, humanCaseId } from "@/lib/types";

async function getCases(): Promise<CaseSummary[]> {
  // Server-component fetch: Next.js rewrites apply only to browser requests,
  // so we talk to FastAPI directly on :8000 here.
  try {
    const res = await fetch("http://localhost:8000/api/cases", {
      cache: "no-store",
    });
    if (!res.ok) return [];
    const data = (await res.json()) as { cases: CaseSummary[] };
    return data.cases;
  } catch {
    return [];
  }
}

export default async function Home() {
  const cases = await getCases();

  return (
    <main className="flex flex-1 justify-center px-6 py-16">
      <div className="w-full max-w-5xl flex flex-col gap-10">
        <header className="flex flex-col gap-3">
          <h1 className="text-4xl font-semibold tracking-tight">
            auto-appeal-agent
          </h1>
          <p className="text-lg text-muted-foreground max-w-2xl">
            Prior Authorization Auto-Appeal Agent — reads a denial letter,
            the patient&apos;s chart, and the insurer&apos;s medical policy,
            and drafts a cited appeal letter where{" "}
            <span className="text-foreground font-medium">
              every factual claim is verified against its source
            </span>
            . Built with Claude Opus 4.7.
          </p>
          <div className="flex gap-2 items-center pt-2 text-sm text-muted-foreground">
            <Badge variant="secondary">Opus 4.7</Badge>
            <span>•</span>
            <span>Verifier strips hallucinated citations before delivery</span>
          </div>
        </header>

        <section className="flex flex-col gap-4">
          <div className="flex items-baseline justify-between">
            <h2 className="text-2xl font-semibold tracking-tight">
              Sample cases
            </h2>
            <span className="text-sm text-muted-foreground">
              Pick a case to run the pipeline end-to-end.
            </span>
          </div>

          {cases.length === 0 ? (
            <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
              No cases found. Make sure the backend is running on{" "}
              <code className="bg-muted px-1 rounded">
                localhost:8000
              </code>{" "}
              (<code>make api</code>) and fixtures are generated (
              <code>make fixtures</code>).
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {cases.map((c) => (
                <Link
                  key={c.case_id}
                  href={`/run/${c.case_id}`}
                  className="group"
                >
                  <Card className="h-full transition-all group-hover:border-foreground/40 group-hover:shadow-sm">
                    <CardHeader>
                      <CardTitle className="text-base">
                        {humanCaseId(c.case_id)}
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="flex flex-col gap-2 text-sm text-muted-foreground">
                      {c.expected_appeal?.key_claims
                        ?.slice(0, 2)
                        .map((claim, i) => (
                          <div key={i} className="flex gap-2">
                            <span className="text-foreground/40">•</span>
                            <span>{claim}</span>
                          </div>
                        ))}
                    </CardContent>
                  </Card>
                </Link>
              ))}
            </div>
          )}
        </section>

        <footer className="text-sm text-muted-foreground border-t pt-6 mt-auto">
          <p>
            Built with Claude Code. See{" "}
            <a
              href="https://github.com/predaaaasaaaaaaa/auto-appeal-agent"
              className="underline hover:text-foreground"
              target="_blank"
              rel="noopener noreferrer"
            >
              the repo
            </a>{" "}
            for architecture, tests, and prior-auth domain docs.
          </p>
        </footer>
      </div>
    </main>
  );
}
