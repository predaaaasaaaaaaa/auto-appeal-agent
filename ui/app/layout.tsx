import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "auto-appeal-agent — Prior Authorization Appeals",
  description:
    "Draft cited, verifier-audited prior-authorization appeals in minutes. Built with Claude Opus 4.7.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col bg-background text-foreground font-sans">
        <TopBar />
        {children}
      </body>
    </html>
  );
}

function TopBar() {
  return (
    <header className="border-b border-border bg-card">
      <div className="mx-auto flex h-12 max-w-[1600px] items-center justify-between gap-4 px-6">
        <div className="flex items-center gap-3">
          <Link href="/" className="flex items-center gap-2">
            <span className="inline-flex h-6 w-6 items-center justify-center rounded-sm bg-primary text-[11px] font-semibold text-primary-foreground">
              AA
            </span>
            <span className="text-sm font-semibold tracking-tight">
              auto-appeal-agent
            </span>
          </Link>
          <span className="text-xs text-muted-foreground">
            Prior Authorization Appeals
          </span>
        </div>
        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-[--color-status-verified]" />
            Backend online
          </span>
          <span className="tabular-nums">Claude Opus 4.7</span>
        </div>
      </div>
    </header>
  );
}
