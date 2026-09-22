import { readNotificationCursor } from "./notification-cursor";

type WSMessageHandler = (data: any) => void;
type WSCloseHandler = (event: CloseEvent) => void;
type WSErrorHandler = (event: Event) => void;

const POLICY_CLOSE_CODES = new Set([1008, 4001, 4003, 4401, 4403]);

export class WSClient {
  private path: string | (() => string);
  private ws: WebSocket | null = null;
  private handlers: Set<WSMessageHandler> = new Set();
  private closeHandlers: Set<WSCloseHandler> = new Set();
  private errorHandlers: Set<WSErrorHandler> = new Set();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private stableConnectionTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private shouldReconnect = true;
  private reconnectAttempts = 0;
  // One-shot streams (e.g. triage) set this false so the server closing the
  // socket after completion does NOT trigger an infinite reconnect loop.
  // Long-lived sockets (notifications) keep it true.
  private autoReconnect: boolean;
  private maxReconnectAttempts: number;
  private heartbeatIntervalMs: number | null;
  private retryForever: boolean;

  constructor(
    path: string | (() => string),
    opts: {
      autoReconnect?: boolean;
      maxReconnectAttempts?: number;
      heartbeatIntervalMs?: number;
      /** Keep long-lived subscriptions retrying with capped backoff after an outage. */
      retryForever?: boolean;
    } = {}
  ) {
    this.autoReconnect = opts.autoReconnect !== false;
    this.maxReconnectAttempts = opts.maxReconnectAttempts ?? 6;
    this.heartbeatIntervalMs = opts.heartbeatIntervalMs ?? null;
    this.retryForever = opts.retryForever === true;
    this.path = path;
  }

  private socketUrl() {
    const path = typeof this.path === "function" ? this.path() : this.path;
    // Connect to the same origin that served the page. The Next.js custom
    // server (server.js) proxies /ws/* upgrades to the backend at runtime via
    // BACKEND_URL. Deriving from window.location avoids the build-time
    // inlining of NEXT_PUBLIC_* vars and works regardless of where the app is
    // served (localhost dev or the in-cluster LoadBalancer).
    if (typeof window !== "undefined") {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      return `${proto}://${window.location.host}${path}`;
    }
    return `ws://localhost:3000${path}`;
  }

  connect() {
    this.shouldReconnect = true;
    this.reconnectAttempts = 0;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.openSocket();
  }

  private openSocket() {
    // Guard CONNECTING too: a socket mid-handshake must not spawn a second
    // connection (duplicate notifications / duplicate triage streams).
    if (this.ws && this.ws.readyState !== WebSocket.CLOSED) return;
    try {
      const ws = new WebSocket(this.socketUrl());
      this.ws = ws;
      ws.onopen = () => {
        if (this.ws !== ws) return;
        if (this.stableConnectionTimer) clearTimeout(this.stableConnectionTimer);
        this.stableConnectionTimer = setTimeout(() => {
          this.reconnectAttempts = 0;
          this.stableConnectionTimer = null;
        }, 60_000);
        this.startHeartbeat(ws);
      };
      ws.onmessage = (ev) => {
        if (this.ws !== ws) return;
        try {
          const data = JSON.parse(ev.data);
          this.handlers.forEach((h) => h(data));
        } catch {
          // ignore non-JSON
        }
      };
      ws.onclose = (event) => {
        if (this.ws !== ws) return;
        this.ws = null;
        if (this.stableConnectionTimer) clearTimeout(this.stableConnectionTimer);
        this.stableConnectionTimer = null;
        this.stopHeartbeat();
        this.closeHandlers.forEach((handler) => handler(event));
        if (POLICY_CLOSE_CODES.has(event.code)) {
          this.shouldReconnect = false;
        }
        // Only auto-reconnect for long-lived sockets. One-shot streams
        // (triage) are closed by the server on purpose after completion;
        // reconnecting would re-trigger the whole analysis in an infinite
        // loop (each reconnect = one real DeepSeek call).
        this.scheduleReconnect();
      };
      ws.onerror = (event) => {
        if (this.ws !== ws) return;
        this.errorHandlers.forEach((handler) => handler(event));
        ws.close();
      };
    } catch {
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect() {
    if (!this.shouldReconnect || !this.autoReconnect || this.reconnectTimer) return;
    if (this.reconnectAttempts >= this.maxReconnectAttempts && !this.retryForever) {
      this.shouldReconnect = false;
      return;
    }

    const baseDelay = Math.min(30_000, 3_000 * 2 ** this.reconnectAttempts);
    const jitter = Math.round(baseDelay * 0.2 * Math.random());
    // Capping the exponent keeps long outages at the same 30-second maximum
    // rather than overflowing the counter or abandoning notifications.
    this.reconnectAttempts = Math.min(this.reconnectAttempts + 1, this.maxReconnectAttempts);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.openSocket();
    }, baseDelay + jitter);
  }

  private startHeartbeat(ws: WebSocket) {
    if (!this.heartbeatIntervalMs) return;
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this.ws !== ws || ws.readyState !== WebSocket.OPEN) return;
      try {
        ws.send("heartbeat");
      } catch {
        ws.close();
      }
    }, this.heartbeatIntervalMs);
  }

  private stopHeartbeat() {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = null;
  }

  onMessage(handler: WSMessageHandler) {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  onClose(handler: WSCloseHandler) {
    this.closeHandlers.add(handler);
    return () => this.closeHandlers.delete(handler);
  }

  onError(handler: WSErrorHandler) {
    this.errorHandlers.add(handler);
    return () => this.errorHandlers.delete(handler);
  }

  disconnect() {
    this.shouldReconnect = false;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    if (this.stableConnectionTimer) clearTimeout(this.stableConnectionTimer);
    this.stableConnectionTimer = null;
    this.stopHeartbeat();
    const ws = this.ws;
    this.ws = null;
    ws?.close();
  }
}

export function createNotificationsWS(userId?: string): WSClient {
  return new WSClient(() => {
    const cursor = userId ? readNotificationCursor(userId) : 0;
    return `/ws/notifications?cursor=${cursor}`;
  }, {
    maxReconnectAttempts: 6,
    heartbeatIntervalMs: 30_000,
    retryForever: true,
  });
}

export function createTicketStreamWS(ticketId: string): WSClient {
  // Triage stream is one-shot: the server sends progress + complete, then
  // closes. Do NOT auto-reconnect.
  return new WSClient(`/ws/tickets/${ticketId}/stream`, { autoReconnect: false });
}
