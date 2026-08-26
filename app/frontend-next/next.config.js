/** @type {import('next').NextConfig} */
const pkg = require("./package.json");

function productionBuildId() {
  const normalized = (process.env.NEXT_PUBLIC_BUILD_SHA || "local")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 96);
  return normalized || "local";
}

const nextConfig = {
  // Keep the public asset path stable through proxies that normalize URL
  // casing, while retaining the immutable source/worktree build stamp.
  generateBuildId: productionBuildId,
  // Inject build-identifiable version info into the client bundle so the
  // footer can show which image is running. `NEXT_PUBLIC_BUILD_SHA` /
  // `NEXT_PUBLIC_BUILD_TIME` are supplied at image build time (Dockerfile).
  env: {
    NEXT_PUBLIC_APP_NAME: pkg.name,
    NEXT_PUBLIC_APP_VERSION: pkg.version,
    NEXT_PUBLIC_BUILD_SHA: process.env.NEXT_PUBLIC_BUILD_SHA || "local",
    NEXT_PUBLIC_BUILD_TIME: process.env.NEXT_PUBLIC_BUILD_TIME || "",
  },
  // NOTE: do NOT use `rewrites()` to proxy /api/* to the backend.
  // Next.js evaluates `rewrites()` at `next build` time and bakes the
  // destination (including the env-derived host) into routes-manifest.json,
  // so a runtime backend-address change is ignored. The Compose frontend only
  // receives its private `http://backend:8000` address when the container starts.
  //
  // API proxying is instead handled at runtime by the catch-all route handler
  // in app/api/[...path]/route.ts, which reads the server-only BACKEND_URL on
  // every request.
};

module.exports = nextConfig;
