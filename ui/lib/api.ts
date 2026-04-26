/**
 * Tiny helper module for talking to the FastAPI backend.
 *
 * Plain-language summary: every browser-side fetch and EventSource
 * URL goes through here so the API-key plumbing lives in exactly
 * one place. If the user has set NEXT_PUBLIC_APPEAL_API_KEY at
 * build time, we attach the key:
 *   - fetch(): X-API-Key request header
 *   - EventSource: api_key query param (EventSource has no public
 *     API for setting headers, so we fall back to the URL)
 *
 * If the key is unset, helpers degrade to plain calls — that
 * matches the backend's no-auth dev mode, so the same UI works
 * in both configurations without code changes.
 *
 * Production note: NEXT_PUBLIC_* vars ship to the browser bundle
 * and are visible to anyone who loads the page. Real production
 * should hide the key behind a server-side proxy (Next.js Route
 * Handler that adds the header before forwarding to FastAPI),
 * but the auth primitive being tested is still the same.
 */

const API_KEY: string | undefined =
  process.env.NEXT_PUBLIC_APPEAL_API_KEY || undefined;

// Direct backend URL for EventSource ONLY. Reason: the Next.js dev
// rewrite proxy buffers text/event-stream responses — it accumulates
// all SSE frames server-side and only flushes them when the upstream
// connection closes. That makes the browser receive every stage's
// "running" and "done" event in the same tick at the END of the
// pipeline, so the visual waiting panel stays at 0s and never shows
// per-agent progress. Fix: open the EventSource straight against
// FastAPI, bypassing the proxy. CORS allows localhost:3000 origin.
//
// Regular fetch()s continue to use relative /api/... paths via the
// proxy because non-streaming responses don't suffer the buffering
// issue and same-origin avoids any CORS preflight surprises.
const API_BASE_URL: string =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

/** HTTP headers to attach to a fetch() call to the backend. */
export function apiHeaders(extra?: HeadersInit): HeadersInit {
  const out: Record<string, string> = {};
  if (extra) {
    if (extra instanceof Headers) {
      extra.forEach((v, k) => {
        out[k] = v;
      });
    } else if (Array.isArray(extra)) {
      for (const [k, v] of extra) out[k] = v;
    } else {
      Object.assign(out, extra);
    }
  }
  if (API_KEY) {
    out["X-API-Key"] = API_KEY;
  }
  return out;
}

/**
 * Build an SSE URL that the browser EventSource can subscribe to.
 * Returns an absolute URL pointing at the FastAPI backend so the
 * stream bypasses the Next.js dev proxy's response buffering.
 * Adds api_key as a query param when configured (EventSource cannot
 * set custom headers from JS).
 */
export function sseUrl(path: string): string {
  const absolute = `${API_BASE_URL}${path}`;
  if (!API_KEY) return absolute;
  const sep = absolute.includes("?") ? "&" : "?";
  return `${absolute}${sep}api_key=${encodeURIComponent(API_KEY)}`;
}
