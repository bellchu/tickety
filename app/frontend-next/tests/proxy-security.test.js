const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
  backendRequestTimeoutMs,
  boundedBody,
  jsonError,
  maxRequestBodyBytes,
  publicForwardingIdentity,
  sanitizedProxyRequestHeaders,
  sanitizedProxyResponseHeaders,
  validateRequestBodyHeaders,
} = require("../lib/proxy-security");

function stream(...chunks) {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(Uint8Array.from(chunk));
      controller.close();
    },
  });
}

test("body limit is finite and bounded", () => {
  assert.equal(maxRequestBodyBytes(undefined), 1_048_576);
  assert.equal(maxRequestBodyBytes("invalid"), 1_048_576);
  assert.equal(maxRequestBodyBytes("1"), 16_384);
  assert.equal(maxRequestBodyBytes("999999999"), 10_485_760);
});

test("backend proxy requests have a bounded operational timeout", () => {
  assert.equal(backendRequestTimeoutMs(undefined), 900_000);
  assert.equal(backendRequestTimeoutMs("invalid"), 900_000);
  assert.equal(backendRequestTimeoutMs("1"), 1_000);
  assert.equal(backendRequestTimeoutMs("999999999"), 1_800_000);
  const route = fs.readFileSync(
    path.join(__dirname, "..", "app", "api", "[...path]", "route.ts"),
    "utf8",
  );
  assert.match(route, /const upstreamSignal = AbortSignal\.timeout\(backendRequestTimeoutMs\(\)\)/);
  assert.match(route, /upstreamSignal\.aborted[\s\S]+504, "upstream_timeout"/);
});

test("proxy errors expose only the stable public code", async () => {
  const response = jsonError(502, "upstream_unavailable");
  assert.equal(response.status, 502);
  assert.deepEqual(await response.json(), { detail: "upstream_unavailable" });
  assert.equal(response.headers.get("content-type"), "application/json");
});

test("deployment public URL survives TLS termination before the container", () => {
  assert.deepEqual(
    publicForwardingIdentity(
      "http://tickety.example.com/api/tickets",
      "https://tickety.example.com",
    ),
    { host: "tickety.example.com", proto: "https" },
  );
  assert.deepEqual(
    publicForwardingIdentity(
      "http://localhost:3000/api/tickets",
      "not-a-url",
    ),
    { host: "localhost:3000", proto: "http" },
  );
});

test("framing validation rejects malformed, conflicting, and oversized lengths", () => {
  const limit = 1024;
  assert.equal(
    validateRequestBodyHeaders(new Headers({ "content-length": "1024" }), limit),
    null,
  );
  assert.deepEqual(
    validateRequestBodyHeaders(new Headers({ "content-length": "1, 2" }), limit),
    { status: 400, detail: "invalid_content_length" },
  );
  assert.deepEqual(
    validateRequestBodyHeaders(
      new Headers({ "content-length": "1", "transfer-encoding": "chunked" }),
      limit,
    ),
    { status: 400, detail: "invalid_content_length" },
  );
  assert.deepEqual(
    validateRequestBodyHeaders(new Headers({ "content-length": "1025" }), limit),
    { status: 413, detail: "request_body_too_large" },
  );
});

test("stream reader accepts the exact limit and rejects the next byte", async () => {
  const exact = await boundedBody(
    { method: "POST", body: stream([1, 2], [3, 4]) },
    4,
  );
  assert.deepEqual(Array.from(new Uint8Array(exact)), [1, 2, 3, 4]);
  await assert.rejects(
    boundedBody({ method: "POST", body: stream([1, 2, 3], [4, 5]) }, 4),
    /request_body_too_large/,
  );
});

test("request proxy strips hop headers but preserves auth and browser origin signals", () => {
  const headers = sanitizedProxyRequestHeaders(
    new Headers({
      authorization: "Bearer session-capability",
      connection: "upgrade, x-private-hop",
      cookie: "tickety_session=opaque",
      host: "attacker.invalid",
      origin: "https://tickety.example.com",
      "proxy-authorization": "private-proxy-secret",
      "sec-fetch-site": "same-origin",
      "transfer-encoding": "chunked",
      upgrade: "websocket",
      "x-private-hop": "must-not-cross-proxy",
      "x-forwarded-host": "attacker.invalid",
      "x-forwarded-for": "203.0.113.99",
      "x-forwarded-proto": "http",
      "cf-connecting-ip": "203.0.113.98",
    }),
    "tickety.example.com",
    "https",
  );
  for (const name of [
    "connection",
    "host",
    "proxy-authorization",
    "transfer-encoding",
    "upgrade",
    "x-private-hop",
    "x-forwarded-for",
    "cf-connecting-ip",
  ]) {
    assert.equal(headers.has(name), false);
  }
  assert.equal(headers.get("authorization"), "Bearer session-capability");
  assert.equal(headers.get("cookie"), "tickety_session=opaque");
  assert.equal(headers.get("origin"), "https://tickety.example.com");
  assert.equal(headers.get("sec-fetch-site"), "same-origin");
  assert.equal(headers.get("x-forwarded-host"), "tickety.example.com");
  assert.equal(headers.get("x-forwarded-proto"), "https");
});

test("response proxy drops stale transport encodings", () => {
  const headers = sanitizedProxyResponseHeaders(
    new Headers({
      connection: "x-upstream-hop",
      "content-encoding": "gzip",
      "content-length": "123",
      "content-type": "application/json",
      "x-upstream-hop": "must-not-cross-proxy",
    }),
  );
  assert.equal(headers.has("content-encoding"), false);
  assert.equal(headers.has("content-length"), false);
  assert.equal(headers.has("connection"), false);
  assert.equal(headers.has("x-upstream-hop"), false);
  assert.equal(headers.get("content-type"), "application/json");
});
