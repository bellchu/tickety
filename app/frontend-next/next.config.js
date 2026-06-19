/** @type {import('next').NextConfig} */
const pkg = require("./package.json");

const nextConfig = {
  // Inject build-identifiable version info into the client bundle so the
  // footer can show which image is running. `NEXT_PUBLIC_BUILD_SHA` /
  // `NEXT_PUBLIC_BUILD_TIME` are supplied at image build time (Dockerfile).
  env: {
    NEXT_PUBLIC_APP_NAME: pkg.name,
    NEXT_PUBLIC_APP_VERSION: pkg.version,
    NEXT_PUBLIC_BUILD_SHA: process.env.NEXT_PUBLIC_BUILD_SHA || "local",
    NEXT_PUBLIC_BUILD_TIME: process.env.NEXT_PUBLIC_BUILD_TIME || "",
  },
  // Cache policy:
  //   - `/_next/static/*` (content-hashed JS/CSS/fonts) -> immutable, 1y.
  //     Next.js already sets this; we restate it so the catch-all below can
  //     exclude it.
  //   - everything else (HTML documents, RSC payloads, /api/*) -> no-cache,
  //     must-revalidate. Next.js otherwise marks statically-rendered App
  //     Router pages with `s-maxage=31536000, stale-while-revalidate`, which
  //     means a new build's HTML is served stale for up to a year and users
  //     see a stale UI after a deploy until they hard-refresh. Marking the
  //     document layer as no-cache forces the browser to revalidate on every
  //     navigation so a freshly rolled pod is picked up immediately, while
  //     the hashed asset chunks stay free to cache forever.
  async headers() {
    return [
      {
        source: "/_next/static/:path*",
        headers: [
          { key: "Cache-Control", value: "public, max-age=31536000, immutable" },
        ],
      },
    ];
  },
  // NOTE: do NOT use `rewrites()` to proxy /api/* to the backend.
  // Next.js evaluates `rewrites()` at `next build` time and bakes the
  // destination (including the env-derived host) into routes-manifest.json,
  // so a runtime NEXT_PUBLIC_API_URL change is ignored. That breaks the
  // in-cluster frontend pod, which only knows the backend address
  // (`http://backend-service:8000`) at pod-startup time.
  //
  // API proxying is instead handled at runtime by the catch-all route handler
  // in app/api/[...path]/route.ts, which reads process.env.NEXT_PUBLIC_API_URL
  // on every request.
};

module.exports = nextConfig;