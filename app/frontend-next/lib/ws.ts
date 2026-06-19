type WSMessageHandler = (data: any) => void;

export class WSClient {
  private url: string;
  private ws: WebSocket | null = null;
  private handlers: Set<WSMessageHandler> = new Set();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private shouldReconnect = true;
  // One-shot streams (e.g. triage) set this false so the server closing the
  // socket after completion does NOT trigger an infinite reconnect loop.
  // Long-lived sockets (notifications) keep it true.
  private autoReconnect: boolean;

  constructor(path: string, opts: { autoReconnect?: boolean } = {}) {
    this.autoReconnect = opts.autoReconnect !== false;
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
    if (this.ws?.readyState === WebSocket.OPEN) return;
    this.shouldReconnect = true;
    try {
      this.ws = new WebSocket(this.url);
      this.ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          this.handlers.forEach((h) => h(data));
        } catch {
          // ignore non-JSON
        }
      };
      this.ws.onclose = () => {
        // Only auto-reconnect for long-lived sockets. One-shot streams
        // (triage) are closed by the server on purpose after completion;
        // reconnecting would re-trigger the whole analysis in an infinite
        // loop (each reconnect = one real DeepSeek call).
        if (this.shouldReconnect && this.autoReconnect) {
          this.reconnectTimer = setTimeout(() => this.connect(), 3000);
        }
      };
      this.ws.onerror = () => {
        this.ws?.close();
      };
    } catch {
      if (this.shouldReconnect) {
        this.reconnectTimer = setTimeout(() => this.connect(), 3000);
      }
    }
  }

  onMessage(handler: WSMessageHandler) {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  disconnect() {
    this.shouldReconnect = false;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
  }
}

export function createNotificationsWS(): WSClient {
  return new WSClient("/ws/notifications");
}

export function createTicketStreamWS(ticketId: string): WSClient {
  // Triage stream is one-shot: the server sends progress + complete, then
  // closes. Do NOT auto-reconnect.
  return new WSClient(`/ws/tickets/${ticketId}/stream`, { autoReconnect: false });
}