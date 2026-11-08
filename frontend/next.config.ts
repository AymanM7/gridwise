import type { NextConfig } from "next";

// Vercel: the API is a separate Vercel project. With API_PROXY_URL set (e.g.
// https://gridwise-api.vercel.app) and NEXT_PUBLIC_API_BASE_URL=/, the browser calls
// same-origin /api/* and Next.js proxies it there, so no CORS and the API URL never changes the bundle.
const apiProxy = process.env.API_PROXY_URL?.replace(/\/$/, "");

const nextConfig: NextConfig = {
  // standalone: minimal self-contained server for the Docker image (frontend/Dockerfile sets
  // NEXT_OUTPUT=standalone). Off for local dev: OneDrive-synced folders break its file tracing.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  async rewrites() {
    return apiProxy ? [{ source: "/api/:path*", destination: `${apiProxy}/api/:path*` }] : [];
  },
};

export default nextConfig;
