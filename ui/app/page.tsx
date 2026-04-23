import Link from "next/link";
import { type CaseSummary, caseMeta } from "@/lib/types";

async function getCases(): Promise<CaseSummary[]> {
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
    <main className="flex flex-1 justify-center px-6 py-6">
      <div className="w-full max-w-[1400px] flex flex-col gap-6">
        <section className="flex flex-col gap-1">
          <h1 className="text-xl font-semibold tracking-tight">
            Appeal worklist
          </h1>
          <p className="text-sm text-muted-foreground">
            Select a denial to review. The agent will read the insurer&apos;s
            denial letter, the patient chart, and the plan&apos;s medical
            policy, then draft a cited appeal letter for physician sign-off.
          </p>
        </section>

        {cases.length === 0 ? (
          <div className="rounded-sm border border-dashed border-border bg-card p-8 text-center text-sm text-muted-foreground">
            No cases on the worklist. Start the backend (
            <code className="bg-muted px-1 rounded-sm">make api</code>) and
            generate fixtures (
            <code className="bg-muted px-1 rounded-sm">make fixtures</code>).
          </div>
        ) : (
          <div className="overflow-hidden rounded-sm border border-border bg-card">
            <table className="w-full text-sm">
              <thead className="bg-muted/60 text-xs uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="px-4 py-2 text-left font-medium">
                    Patient
                  </th>
                  <th className="px-4 py-2 text-left font-medium">
                    Service denied
                  </th>
                  <th className="px-4 py-2 text-left font-medium">Plan</th>
                  <th className="px-4 py-2 text-left font-medium">
                    Denial date
                  </th>
                  <th className="px-4 py-2 text-left font-medium">
                    Specialty
                  </th>
                  <th className="px-4 py-2 text-right font-medium">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {cases.map((c) => {
                  const meta = caseMeta(c.case_id);
                  return (
                    <tr
                      key={c.case_id}
                      className="hover:bg-muted/40 transition-colors"
                    >
                      <td className="px-4 py-3">
                        <div className="flex flex-col">
                          <span className="font-medium">
                            {meta?.patient_name ?? c.case_id}
                          </span>
                          <span className="text-xs text-muted-foreground tabular-nums">
                            DOB {meta?.date_of_birth ?? "—"} · Member{" "}
                            {meta?.member_id ?? "—"}
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {meta?.service ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {meta?.plan ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground tabular-nums">
                        {meta?.denial_date ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {meta?.clinical_domain ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Link
                          href={`/run/${c.case_id}`}
                          className="inline-flex items-center rounded-sm border border-primary bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90"
                        >
                          Draft appeal →
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <aside className="flex flex-col gap-2 rounded-sm border border-border bg-muted/40 p-4 text-xs text-muted-foreground">
          <div className="font-medium text-foreground">
            How this works
          </div>
          <ol className="list-decimal pl-5 leading-relaxed">
            <li>
              Six specialist agents read the denial letter, the plan&apos;s
              medical policy, the patient chart, and relevant clinical
              guidelines.
            </li>
            <li>
              A Letter Writer drafts the appeal, attaching a citation receipt
              to every factual claim.
            </li>
            <li>
              A separate Verifier re-reads each citation against its source
              and strips anything it cannot confirm verbatim. Nothing
              unverified reaches the final letter.
            </li>
          </ol>
        </aside>
      </div>
    </main>
  );
}
