type WSMessageHandler = (data: any) => void;
type WSCloseHandler = (event: CloseEvent) => void;
type WSErrorHandler = (event: Event) => void;

const POLICY_CLOSE_CODES = new Set([1008, 4001, 4003, 4401, 4403]);

export class WSClient {
  private url: string;
  private ws: WebSocket | null = null;
  private handlers: Set<WSMessageHandler> = new Set();
  private closeHandlers: Set<WSCloseHandler> = new Set();
  private errorHandlers: Set<WSErrorHandler> = new Set();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private stableConnectionTimer: ReturnType<typeof setTimeout> | null = null;
  private shouldReconnect = true;
  private reconnectAttempts = 0;
  // One-shot streams (e.g. triage) set this false so the server closing the
  // socket after completion does NOT trigger an infinite reconnect loop.
  // Long-lived sockets (notifications) keep it true.
  private autoReconnect: boolean;
  private maxReconnectAttempts: number;

  constructor(
    path: string,
    opts: { autoReconnect?: boolean; maxReconnectAttempts?: number } = {}
  ) {
    this.autoReconnect = opts.autoReconnect !== false;
    this.maxReconnectAttempts = opts.maxReconnectAttempts ?? 6;
    // Connect to the same origin that served the page. The Next.js custom
    // server (server.js) proxies /ws/* upgrades to the backend at runtime via
    // BACKEND_URL. Deriving from window.location avoids the build-time
    // inlining of NEXT_PUBLIC_* vars and works regardless of where the app is
    // served (localhost dev or the in-cluster LoadBalancer).
    if (typeof window !== "undefined") {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      this.url = `${proto}://${window.location.host}${path}`;
    } else {
      this.url = `ws://localhost:3000${path}`;
    }
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
      const ws = new WebSocket(this.url);
      this.ws = ws;
      ws.onopen = () => {
        if (this.stableConnectionTimer) clearTimeout(this.stableConnectionTimer);
        this.stableConnectionTimer = setTimeout(() => {
          this.reconnectAttempts = 0;
          this.stableConnectionTimer = null;
        }, 60_000);
      };
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          this.handlers.forEach((h) => h(data));
        } catch {
          // ignore non-JSON
        }
      };
      ws.onclose = (event) => {
        if (this.ws === ws) this.ws = null;
        if (this.stableConnectionTimer) clearTimeout(this.stableConnectionTimer);
        this.stableConnectionTimer = null;
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
        this.errorHandlers.forEach((handler) => handler(event));
        ws.close();
      };
    } catch {
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect() {
    if (!this.shouldReconnect || !this.autoReconnect || this.reconnectTimer) return;
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      this.shouldReconnect = false;
      return;
    }

    const baseDelay = Math.min(30_000, 3_000 * 2 ** this.reconnectAttempts);
    const jitter = Math.round(baseDelay * 0.2 * Math.random());
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.openSocket();
    }, baseDelay + jitter);
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
    this.ws?.close();
    this.ws = null;
  }
}

export function createNotificationsWS(): WSClient {
  return new WSClient("/ws/notifications", { maxReconnectAttempts: 6 });
}

export function createTicketStreamWS(ticketId: string): WSClient {
  // Triage stream is one-shot: the server sends progress + complete, then
  // closes. Do NOT auto-reconnect.
  return new WSClient(`/ws/tickets/${ticketId}/stream`, { autoReconnect: false });
}
