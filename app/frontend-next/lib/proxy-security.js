const HOP_BY_HOP_REQUEST_HEADERS = [
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
];

function connectionOptionHeaders(headers) {
  return (headers.get("connection") || "")
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter((value) => /^[!#$%&'*+.^_`|~0-9a-z-]+$/.test(value));
}

function maxRequestBodyBytes(raw = process.env.MAX_REQUEST_BODY_BYTES) {
  const configured = Number.parseInt(raw || "1048576", 10);
  if (!Number.isFinite(configured)) return 1_048_576;
  return Math.max(16_384, Math.min(configured, 10_485_760));
}

function jsonError(status, detail) {
  return new Response(JSON.stringify({ detail }), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/**
 * Use the deployment-owned public URL for forwarding identity. TLS commonly
 * terminates before the Next.js container, so req.nextUrl can legitimately be http
 * even while the browser origin is https. Falling back to the request URL
 * keeps local development usable when SITE_URL is absent or invalid.
 *
 * @param {string | URL} requestUrl
 * @param {string | undefined} configuredSiteUrl
 */
function publicForwardingIdentity(requestUrl, configuredSiteUrl) {
  let url;
  try {
    const configured = configuredSiteUrl
      ? new URL(configuredSiteUrl)
      : null;
    if (
      configured &&
      ["http:", "https:"].includes(configured.protocol) &&
      configured.host
    ) {
      url = configured;
    }
  } catch {
    // Invalid deployment configuration falls back to the actual request URL.
  }
  if (!url) url = new URL(String(requestUrl));
  return { host: url.host, proto: url.protocol.replace(":", "") };
}

/**
 * Validate framing headers before reading a body. A transfer-encoded request
 * without Content-Length remains valid; its decoded stream is bounded below.
 *
 * @param {Headers} headers
 * @param {number} limit
 * @returns {{status: number, detail: string} | null}
 */
function validateRequestBodyHeaders(headers, limit) {
  const contentLength = headers.get("content-length");
  const transferEncoding = headers.get("transfer-encoding");
  if (contentLength) {
    if (!/^\d+$/.test(contentLength) || transferEncoding) {
      return { status: 400, detail: "invalid_content_length" };
    }
    if (Number.parseInt(contentLength, 10) > limit) {
      return { status: 413, detail: "request_body_too_large" };
    }
  }
  return null;
}

/**
 * @param {{method: string, body: ReadableStream<Uint8Array> | null}} req
 * @param {number} limit
 * @returns {Promise<ArrayBuffer | undefined>}
 */
async function boundedBody(req, limit) {
  if (["GET", "HEAD"].includes(req.method) || !req.body) return undefined;

  const reader = req.body.getReader();
  const chunks = [];
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

  const body = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body.buffer;
}

/**
 * @param {Headers} source
 * @param {string} forwardedHost
 * @param {string} forwardedProto
 */
function sanitizedProxyRequestHeaders(source, forwardedHost, forwardedProto) {
  const headers = new Headers(source);
  for (const header of connectionOptionHeaders(headers)) headers.delete(header);
  for (const header of HOP_BY_HOP_REQUEST_HEADERS) headers.delete(header);
  // Caller-controlled network identity must not cross the application proxy.
  // Tickety OPS Tower uses application-owned global/reporter quotas instead of trusting
  // forwarding headers that may be spoofed on a directly reachable origin.
  for (const header of [
    "cf-connecting-ip",
    "forwarded",
    "true-client-ip",
    "x-forwarded-for",
    "x-real-ip",
  ]) headers.delete(header);
  headers.set("x-forwarded-host", forwardedHost);
  headers.set("x-forwarded-proto", forwardedProto);
  return headers;
}

/** @param {Headers} source */
function sanitizedProxyResponseHeaders(source) {
  const headers = new Headers(source);
  for (const header of connectionOptionHeaders(headers)) headers.delete(header);
  for (const header of [
    ...HOP_BY_HOP_REQUEST_HEADERS,
    "content-encoding",
  ]) {
    headers.delete(header);
  }
  return headers;
}

module.exports = {
  boundedBody,
  jsonError,
  maxRequestBodyBytes,
  publicForwardingIdentity,
  sanitizedProxyRequestHeaders,
  sanitizedProxyResponseHeaders,
  validateRequestBodyHeaders,
};
