import { NextRequest } from "next/server";

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

type Ctx = { params: { path: string[] } };

async function proxy(req: NextRequest, ctx: Ctx) {
  const path = (ctx.params.path || []).map(encodeURIComponent).join("/");
  const search = req.nextUrl.search; // includes leading "?" or ""
  const url = `${BACKEND}/${path}${search}`;

  // Hop-by-hop / host headers must not be forwarded verbatim.
  const headers = new Headers(req.headers);
  headers.delete("host");
  headers.delete("content-length"); // fetch recomputes from the body

  const init: RequestInit & { duplex?: "half" } = {
    method: req.method,
    headers,
    // GET/HEAD must not carry a body.
    body: ["GET", "HEAD"].includes(req.method) ? undefined : req.body,
    duplex: "half",
    cache: "no-store",
    redirect: "manual",
  };

  try {
    const upstream = await fetch(url, init);
    const respHeaders = new Headers(upstream.headers);
    // We pass through the already-decoded body; drop transport encoding.
    respHeaders.delete("content-encoding");
    respHeaders.delete("content-length");
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: respHeaders,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return new Response(
      JSON.stringify({ error: "proxy_failed", detail: message, upstream: url }),
      { status: 502, headers: { "content-type": "application/json" } }
    );
  }
}

export const GET = (req: NextRequest, ctx: Ctx) => proxy(req, ctx);
export const POST = (req: NextRequest, ctx: Ctx) => proxy(req, ctx);
export const PUT = (req: NextRequest, ctx: Ctx) => proxy(req, ctx);
export const PATCH = (req: NextRequest, ctx: Ctx) => proxy(req, ctx);
export const DELETE = (req: NextRequest, ctx: Ctx) => proxy(req, ctx);