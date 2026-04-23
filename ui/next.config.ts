import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
