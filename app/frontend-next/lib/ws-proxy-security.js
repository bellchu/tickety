function createWebSocketUpgradeHandler(proxy) {
  return (req, socket, head) => {
    const url = req.url || "";
    if (url.startsWith("/ws/")) {
      sanitizeWebSocketForwardingHeaders(req);
      // Pass the original request object so Cookie and Origin still reach the
      // backend after spoofable forwarding metadata has been overwritten.
      proxy.ws(req, socket, head);
      return;
    }
    socket.destroy();
  };
}

function sanitizeWebSocketForwardingHeaders(req) {
  const headers = req.headers || (req.headers = {});
  const connectionOptions = String(headers.connection || "")
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter((value) => /^[!#$%&'*+.^_`|~0-9a-z-]+$/.test(value));
  for (const name of connectionOptions) {
    if (name !== "upgrade") delete headers[name];
  }

  const host = String(headers.host || "").split(",", 1)[0].trim();
  let proto = req.socket && req.socket.encrypted ? "https" : "http";
  try {
    const origin = new URL(String(headers.origin || ""));
    if (origin.protocol === "http:" || origin.protocol === "https:") {
      proto = origin.protocol.slice(0, -1);
    }
  } catch {
    // Missing/malformed Origin is rejected by the backend; retain transport.
  }
  delete headers["x-forwarded-host"];
  delete headers["x-forwarded-proto"];
  if (host) headers["x-forwarded-host"] = host;
  headers["x-forwarded-proto"] = proto;
}

function webSocketProxyErrorKind(error) {
  return error && typeof error.name === "string" && error.name
    ? error.name
    : "unknown";
}

module.exports = {
  createWebSocketUpgradeHandler,
  sanitizeWebSocketForwardingHeaders,
  webSocketProxyErrorKind,
};
