const assert = require("node:assert/strict");
const test = require("node:test");

const {
  createWebSocketUpgradeHandler,
  sanitizeWebSocketForwardingHeaders,
  webSocketProxyErrorKind,
} = require("../lib/ws-proxy-security");

test("WebSocket handler forwards only ws paths with original auth headers", () => {
  const calls = [];
  const proxy = {
    ws(req, socket, head) {
      calls.push({ req, socket, head });
    },
  };
  const handler = createWebSocketUpgradeHandler(proxy);
  const req = {
    url: "/ws/tickets/ticket-1/stream",
    headers: {
      connection: "upgrade, x-forwarded-host",
      cookie: "tickety_session=opaque",
      host: "tickety.situ.io",
      origin: "https://tickety.situ.io",
      "x-forwarded-host": "evil.invalid",
      "x-forwarded-proto": "http",
    },
  };
  const socket = { destroy() { throw new Error("must not destroy"); } };
  const head = Buffer.alloc(0);

  handler(req, socket, head);

  assert.equal(calls.length, 1);
  assert.equal(calls[0].req, req);
  assert.equal(calls[0].req.headers.cookie, "tickety_session=opaque");
  assert.equal(calls[0].req.headers.origin, "https://tickety.situ.io");
  assert.equal(calls[0].req.headers["x-forwarded-host"], "tickety.situ.io");
  assert.equal(calls[0].req.headers["x-forwarded-proto"], "https");
});

test("WebSocket forwarding metadata cannot follow a spoofed Origin", () => {
  const req = {
    headers: {
      host: "tickety.situ.io",
      origin: "https://evil.invalid",
      "x-forwarded-host": "evil.invalid",
      "x-forwarded-proto": "https",
    },
    socket: {},
  };

  sanitizeWebSocketForwardingHeaders(req);

  assert.equal(req.headers["x-forwarded-host"], "tickety.situ.io");
  assert.equal(req.headers["x-forwarded-proto"], "https");
  assert.notEqual(
    `${req.headers["x-forwarded-proto"]}://${req.headers["x-forwarded-host"]}`,
    req.headers.origin,
  );
});

test("WebSocket handler destroys upgrades outside the ws namespace", () => {
  let destroyed = false;
  const proxy = { ws() { throw new Error("must not proxy"); } };
  const handler = createWebSocketUpgradeHandler(proxy);

  handler(
    { url: "/api/version", headers: {} },
    { destroy() { destroyed = true; } },
    Buffer.alloc(0),
  );

  assert.equal(destroyed, true);
});

test("WebSocket proxy error logging exposes only an exception kind", () => {
  const secret = "https://user:password@backend.invalid/private";
  const error = new Error(secret);
  assert.equal(webSocketProxyErrorKind(error), "Error");
  assert.equal(webSocketProxyErrorKind({ message: secret }), "unknown");
  assert.notEqual(webSocketProxyErrorKind(error), secret);
});
