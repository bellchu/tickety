/**
 * Custom Next.js server.
 *
 * Why a custom server? Next.js route handlers can proxy HTTP (/api/* is handled
 * by app/api/[...path]/route.ts), but they CANNOT proxy WebSocket upgrade
 * requests. The browser's WS client connects same-origin to /ws/* (see
 * lib/ws.ts), so something in this process must accept the HTTP `upgrade`
 * event for /ws/* and tunnel it to the backend.
 *
 * BACKEND_URL is a server-only (non-NEXT_PUBLIC) env var read at runtime, so
 * the in-cluster address (http://backend-service:8000) is honoured — the same
 * trick the /api route handler uses.
 */
const http = require("http");
const { parse } = require("url");
const next = require("next");
const httpProxy = require("http-proxy");

const dev = process.env.NODE_ENV !== "production";
const port = parseInt(process.env.PORT || "3000", 10);
const hostname = process.env.HOSTNAME || "0.0.0.0";

const BACKEND = process.env.BACKEND_URL || "http://localhost:8000";

const app = next({ dev, hostname, port });
const handle = app.getRequestHandler();

app.prepare().then(() => {
  const proxy = httpProxy.createProxyServer({
    target: BACKEND,
    ws: true,
    changeOrigin: true,
    secure: false,
  });

  proxy.on("error", (err, _req, target) => {
    console.error("[ws-proxy] error:", err.message, "target:", target && target.url);
    // If the socket is still open, destroy it so the client reconnects.
    const sock = target && target.socket;
    if (sock && !sock.destroyed) sock.destroy();
  });

  const server = http.createServer((req, res) => {
    const parsedUrl = parse(req.url, true);
    handle(req, res, parsedUrl);
  });

  // WebSocket upgrade handling.
  server.on("upgrade", (req, socket, head) => {
    const url = req.url || "";
    if (url.startsWith("/ws/")) {
      proxy.ws(req, socket, head);
    } else {
      // Only /ws/* is proxied; refuse anything else.
      socket.destroy();
    }
  });

  server.listen(port, hostname, (err) => {
    if (err) throw err;
    console.log(
      `> Ready on http://${hostname}:${port} (dev=${dev}) ` +
        `ws proxy /ws/* -> ${BACKEND}`
    );
  });
});