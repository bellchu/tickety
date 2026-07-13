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

type Ctx = { params: Promise<{ path: string[] }> };

function maxRequestBodyBytes() {
  const configured = Number.parseInt(
    process.env.MAX_REQUEST_BODY_BYTES || "1048576",
    10,
  );
  if (!Number.isFinite(configured)) return 1_048_576;
  return Math.max(16_384, Math.min(configured, 10_485_760));
}

function jsonError(status: number, detail: string) {
  return new Response(JSON.stringify({ detail }), {
    status,
    headers: { "content-type": "application/json" },
  });
}

async function boundedBody(
  req: NextRequest,
  limit: number,
): Promise<ArrayBuffer | undefined> {
  if (["GET", "HEAD"].includes(req.method) || !req.body) return undefined;

  const reader = req.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!value) continue;
    total += value.byteLength;
    if (total > limit) {
      await reader.cancel("request_body_too_large");
      throw new RangeError("request_body_too_large");
    }
    chunks.push(value);
  }

  const body: Uint8Array<ArrayBuffer> = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body.buffer;
}

async function proxy(req: NextRequest, ctx: Ctx) {
  const params = await ctx.params;
  const path = (params.path || []).map(encodeURIComponent).join("/");
  const search = req.nextUrl.search; // includes leading "?" or ""
  const url = `${BACKEND}/${path}${search}`;

  const maxBodyBytes = maxRequestBodyBytes();
  const contentLength = req.headers.get("content-length");
  const transferEncoding = req.headers.get("transfer-encoding");
  if (contentLength) {
    if (!/^\d+$/.test(contentLength) || transferEncoding) {
      return jsonError(400, "invalid_content_length");
    }
    if (Number.parseInt(contentLength, 10) > maxBodyBytes) {
      return jsonError(413, "request_body_too_large");
    }
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
  const headers = new Headers(req.headers);
  for (const header of [
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
  ]) {
    headers.delete(header);
  }
  headers.set("x-forwarded-host", req.nextUrl.host);
  headers.set("x-forwarded-proto", req.nextUrl.protocol.replace(":", ""));

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
