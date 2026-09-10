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

function browserSecurityHeaders() {
  const scriptSources = ["'self'", "'unsafe-inline'"];
  if (process.env.NODE_ENV !== "production") scriptSources.push("'unsafe-eval'");
  const contentSecurityPolicy = [
    "default-src 'self'",
    "base-uri 'self'",
    `script-src ${scriptSources.join(" ")}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https:",
    "font-src 'self' data:",
    "connect-src 'self' wss:",
    "worker-src 'self' blob:",
    "object-src 'none'",
    "frame-src 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    "manifest-src 'self'",
  ].join("; ");

  return [
    { key: "Content-Security-Policy", value: contentSecurityPolicy },
    {
      key: "Strict-Transport-Security",
      value: "max-age=31536000; includeSubDomains",
    },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "X-Frame-Options", value: "DENY" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    {
      key: "Permissions-Policy",
      value:
        "accelerometer=(), autoplay=(), camera=(), geolocation=(), " +
        "gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()",
    },
  ];
}

const nextConfig = {
  poweredByHeader: false,
  // Keep the public asset path stable through proxies that normalize URL
  // casing, while retaining the immutable source/worktree build stamp.
  generateBuildId: productionBuildId,
  async headers() {
    return [{ source: "/(.*)", headers: browserSecurityHeaders() }];
  },
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
