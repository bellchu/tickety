import { NextRequest } from "next/server";
import {
  boundedBody,
  jsonError,
  maxRequestBodyBytes,
  sanitizedProxyRequestHeaders,
  sanitizedProxyResponseHeaders,
  validateRequestBodyHeaders,
} from "@/lib/proxy-security";

/**
 * Runtime API proxy.
 *
 * The browser calls same-origin `/api/...` (see lib/api.ts). This catch-all
 * route handler forwards each request to the backend at
 * `process.env.NEXT_PUBLIC_API_URL` — which is read at RUNTIME, not build time.
 *
 * We intentionally do NOT rely on next.config.js `rewrites()`, because Next.js
 * evaluates `rewrites()` at `next build` and bakes the destination into the
 * routes manifest. A build-time destination breaks when the same image runs in
 * different environments (the in-cluster `backend-service` address is only
 * known at pod-startup time). A route handler reads the env on every request,
 * so the k8s pod env `NEXT_PUBLIC_API_URL=http://backend-service:8000` is
 * honoured.
 */
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

// Server-only env (NOT NEXT_PUBLIC_*). Next.js inlines NEXT_PUBLIC_* vars at
// build time, which would bake in the build host and ignore the runtime pod
// env. A plain (non-public) var is read from process.env at request time.
const BACKEND =
  process.env.BACKEND_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000";

type Ctx = { params: Promise<{ path: string[] }> };

async function proxy(req: NextRequest, ctx: Ctx) {
  const params = await ctx.params;
  const path = (params.path || []).map(encodeURIComponent).join("/");
  const search = req.nextUrl.search; // includes leading "?" or ""
  const url = `${BACKEND}/${path}${search}`;

  const maxBodyBytes = maxRequestBodyBytes();
  const framingError = validateRequestBodyHeaders(req.headers, maxBodyBytes);
  if (framingError) {
    return jsonError(framingError.status, framingError.detail);
  }

  let body: ArrayBuffer | undefined;
  try {
    body = await boundedBody(req, maxBodyBytes);
  } catch (err) {
    if (err instanceof RangeError && err.message === "request_body_too_large") {
      return jsonError(413, "request_body_too_large");
    }
    return jsonError(400, "invalid_request_body");
  }

  // Hop-by-hop / host headers must not be forwarded verbatim. Preserve the
  // browser's Origin and Sec-Fetch-* headers so backend CSRF checks see the
  // real caller instead of a synthetic same-origin value from this proxy.
  const headers = sanitizedProxyRequestHeaders(
    req.headers,
    req.nextUrl.host,
    req.nextUrl.protocol.replace(":", ""),
  );

  const init: RequestInit & { duplex?: "half" } = {
    method: req.method,
    headers,
    body,
    duplex: "half",
    cache: "no-store",
    redirect: "manual",
  };

  try {
    const upstream = await fetch(url, init);
    // We pass through the already-decoded body; drop transport encoding.
    const respHeaders = sanitizedProxyResponseHeaders(upstream.headers);
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: respHeaders,
    });
  } catch (err) {
    console.error(
      "[api-proxy] upstream request failed kind=",
      err instanceof Error ? err.name : "unknown",
    );
    return jsonError(502, "upstream_unavailable");
  }
}

export const GET = (req: NextRequest, ctx: Ctx) => proxy(req, ctx);
export const POST = (req: NextRequest, ctx: Ctx) => proxy(req, ctx);
export const PUT = (req: NextRequest, ctx: Ctx) => proxy(req, ctx);
export const PATCH = (req: NextRequest, ctx: Ctx) => proxy(req, ctx);
export const DELETE = (req: NextRequest, ctx: Ctx) => proxy(req, ctx);
