import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // React Strict Mode is OFF deliberately. It is a dev-only debug aid
  // that double-invokes effects to catch impure components. For the
  // run page, that double-invocation opened TWO EventSource
  // connections per page load, each kicking off a full pipeline run
  // against Anthropic — burning ~$1 of API spend per page open with
  // no upside. The setTimeout(0) trick that worked in older Next /
  // React versions does not survive Next.js 16 + React 19 timing.
  // Production has Strict Mode off by default; this matches that.
  reactStrictMode: false,
  // Proxy all /api/* browser requests to the FastAPI backend on :8000.
  // That way the client-side EventSource in app/run/[case_id]/page.tsx can
  // open a same-origin stream and we skip CORS entirely in the browser.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
