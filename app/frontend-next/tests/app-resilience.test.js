const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

const root = path.join(__dirname, "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");

function loadWs() {
  const filename = path.join(root, "lib", "ws.ts");
  const output = ts.transpileModule(read("lib", "ws.ts"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
    fileName: filename,
  }).outputText;
  const loaded = { exports: {} };
  new Function("exports", "module", "require", output)(loaded.exports, loaded, (name) => {
    if (name === "./notification-cursor") {
      return {
        readNotificationCursor: userId => {
          const raw = global.window?.localStorage?.getItem(`tickety.notifications.cursor.${userId}`);
          return typeof raw === "string" && /^(?:0|[1-9][0-9]{0,15})$/.test(raw) ? Number(raw) : 0;
        },
      };
    }
    throw new Error(`Unexpected module: ${name}`);
  });
  return loaded.exports;
}

test("root app supplies optimized fonts and route recovery conventions", () => {
  const layout = read("app", "layout.tsx");
  const fonts = read("app", "fonts.ts");
  const globals = read("app", "globals.css");

  assert.match(layout, /dmSans\.variable/);
  assert.match(fonts, /next\/font\/google/);
  assert.doesNotMatch(globals, /fonts\.googleapis\.com/);
  for (const filename of ["loading.tsx", "error.tsx", "global-error.tsx", "not-found.tsx"]) {
    assert.equal(fs.existsSync(path.join(root, "app", filename)), true, `${filename} exists`);
  }
  assert.match(read("app", "error.tsx"), /onClick=\{reset\}/);
  assert.match(read("app", "global-error.tsx"), /onClick=\{reset\}/);
  assert.match(read("components", "layout", "AppShell.tsx"), /realtimeEnabled=\{authContext\?\.auth_kind === "session"\}/);
});

test("protected shell revalidates an externally changed session before rendering cached data", () => {
  const shell = read("components", "layout", "AppShell.tsx");
  assert.match(shell, /const validateAuthenticatedSession = useCallback/);
  assert.match(shell, /setAuthState\("checking"\)/);
  assert.match(shell, /authValidationGeneration/);
  assert.match(shell, /window\.addEventListener\("focus", revalidateWhenVisible\)/);
  assert.match(shell, /document\.addEventListener\("visibilitychange", revalidateWhenVisible\)/);
  assert.match(shell, /crossesAuthorizationBoundary\(previous, context\).*?queryClient\.clear\(\)/s);
});

test("a closed mobile sidebar is removed from both focus and accessibility navigation", () => {
  const shell = read("components", "layout", "AppShell.tsx");
  const sidebar = read("components", "layout", "Sidebar.tsx");

  assert.match(shell, /window\.matchMedia\("\(min-width: 1024px\)"\)/);
  assert.match(shell, /inactive=\{!hasDesktopSidebar && !navigationOpen\}/);
  assert.match(sidebar, /aria-hidden=\{inactive \|\| undefined\}/);
  assert.match(sidebar, /inert=\{inactive \|\| undefined\}/);
  assert.match(sidebar, /aria-modal=\{open \? "true" : undefined\}/);
});

test("explicit drawer dismissal restores Menu focus without overriding navigation focus", () => {
  const shell = read("components", "layout", "AppShell.tsx");
  const sidebar = read("components", "layout", "Sidebar.tsx");

  assert.match(shell, /const closeNavigation = useCallback\(\(\) => \{\s*setNavigationOpen\(false\);\s*requestAnimationFrame\(\(\) => menuButtonRef\.current\?\.focus\(\)\);/);
  assert.match(shell, /onClose=\{closeNavigation\}/);
  assert.match(shell, /onNavigate=\{\(\) => setNavigationOpen\(false\)\}/);
  assert.match(shell, /onClick=\{closeNavigation\}/);
  assert.equal(sidebar.match(/onClick=\{onClose\}/g)?.length, 1, "only the close button explicitly dismisses the drawer");
  assert.ok((sidebar.match(/onClick=\{onNavigate\}/g)?.length ?? 0) >= 4, "navigation links close without forcing Menu focus");
  assert.match(sidebar, /onNavigate=\{onNavigate\}/);
});

test("tier promotions defer behind standard dialogs instead of creating two aria-modal boundaries", () => {
  const dialog = read("components", "ui", "Dialog.tsx");
  const experience = read("components", "layout", "AppExperience.tsx");
  const promotion = read("components", "engagement", "TierPromotionModal.tsx");
  const followUp = read("components", "agent", "AgentWorkspace.tsx");

  assert.match(dialog, /modalCategory\?: "standard" \| "engagement"/);
  assert.match(dialog, /if \(!open \|\| modalCategory !== "standard"\) return;/);
  assert.match(dialog, /registerStandardDialog\(\)/);
  assert.match(experience, /useState<number \| null>\(null\)/);
  assert.match(experience, /useLayoutEffect\(\(\) =>/);
  assert.match(experience, /subscribeToStandardDialogs/);
  assert.match(experience, /showTierPromotion && canPresentEngagementModal\(standardDialogCount\)/);
  assert.match(promotion, /modalCategory="engagement"/);
  assert.match(followUp, /<FollowUpDialog/);
});

test("notification websocket stops on policy rejection and backs off transient failures", () => {
  const originalWindow = global.window;
  const originalWebSocket = global.WebSocket;
  const originalSetTimeout = global.setTimeout;
  const originalClearTimeout = global.clearTimeout;
  const originalRandom = Math.random;
  const timers = [];

  class FakeWebSocket {
    static CLOSED = 3;
    static instances = [];
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      FakeWebSocket.instances.push(this);
    }
    close() { this.readyState = FakeWebSocket.CLOSED; }
    emitClose(code) {
      this.readyState = FakeWebSocket.CLOSED;
      this.onclose?.({ code });
    }
  }

  global.window = { location: { protocol: "https:", host: "tickety.example.com" } };
  global.WebSocket = FakeWebSocket;
  global.setTimeout = (callback, delay) => {
    const timer = { callback, delay, cleared: false };
    timers.push(timer);
    return timer;
  };
  global.clearTimeout = (timer) => { if (timer) timer.cleared = true; };
  Math.random = () => 0;

  try {
    const { WSClient } = loadWs();
    const policyClient = new WSClient("/ws/notifications");
    policyClient.connect();
    FakeWebSocket.instances.at(-1).emitClose(1008);
    assert.equal(timers.filter((timer) => !timer.cleared).length, 0);

    const transientClient = new WSClient("/ws/notifications");
    transientClient.connect();
    FakeWebSocket.instances.at(-1).emitClose(1013);
    assert.equal(timers.at(-1).delay, 3_000);
    timers.at(-1).callback();
    FakeWebSocket.instances.at(-1).emitClose(1013);
    assert.equal(timers.at(-1).delay, 6_000);
    transientClient.disconnect();
    assert.equal(timers.at(-1).cleared, true);

    const persistentClient = new WSClient("/ws/notifications", { maxReconnectAttempts: 1, retryForever: true });
    persistentClient.connect();
    FakeWebSocket.instances.at(-1).emitClose(1013);
    timers.at(-1).callback();
    FakeWebSocket.instances.at(-1).emitClose(1013);
    assert.equal(timers.at(-1).delay, 6_000, "persistent subscriptions keep reconnecting after their initial retry budget");
    persistentClient.disconnect();
  } finally {
    global.window = originalWindow;
    global.WebSocket = originalWebSocket;
    global.setTimeout = originalSetTimeout;
    global.clearTimeout = originalClearTimeout;
    Math.random = originalRandom;
  }
});

test("notification websocket heartbeats keep an accepted subscription active and stop on close", () => {
  const originalWindow = global.window;
  const originalWebSocket = global.WebSocket;
  const originalSetTimeout = global.setTimeout;
  const originalClearTimeout = global.clearTimeout;
  const originalSetInterval = global.setInterval;
  const originalClearInterval = global.clearInterval;
  const intervals = [];

  class FakeWebSocket {
    static OPEN = 1;
    static CLOSED = 3;
    static instances = [];
    constructor() {
      this.readyState = 0;
      this.sent = [];
      FakeWebSocket.instances.push(this);
    }
    send(message) { this.sent.push(message); }
    close() { this.readyState = FakeWebSocket.CLOSED; }
    emitClose(code) {
      this.readyState = FakeWebSocket.CLOSED;
      this.onclose?.({ code });
    }
  }

  global.window = { location: { protocol: "https:", host: "tickety.example.com" } };
  global.WebSocket = FakeWebSocket;
  global.setTimeout = () => ({ cleared: false });
  global.clearTimeout = () => {};
  global.setInterval = (callback, delay) => {
    const timer = { callback, delay, cleared: false };
    intervals.push(timer);
    return timer;
  };
  global.clearInterval = (timer) => { if (timer) timer.cleared = true; };

  try {
    const { createNotificationsWS } = loadWs();
    const client = createNotificationsWS();
    client.connect();
    const socket = FakeWebSocket.instances.at(-1);
    socket.readyState = FakeWebSocket.OPEN;
    socket.onopen();

    assert.equal(intervals.length, 1);
    assert.equal(intervals[0].delay, 30_000);
    intervals[0].callback();
    assert.deepEqual(socket.sent, ["heartbeat"]);

    socket.emitClose(1008);
    assert.equal(intervals[0].cleared, true);
  } finally {
    global.window = originalWindow;
    global.WebSocket = originalWebSocket;
    global.setTimeout = originalSetTimeout;
    global.clearTimeout = originalClearTimeout;
    global.setInterval = originalSetInterval;
    global.clearInterval = originalClearInterval;
  }
});

test("notification reconnect resolves the latest user-scoped replay cursor", () => {
  const originalWindow = global.window;
  const originalWebSocket = global.WebSocket;
  const originalSetTimeout = global.setTimeout;
  const originalClearTimeout = global.clearTimeout;
  const values = new Map([["tickety.notifications.cursor.agent-a", "7"]]);
  const timers = [];
  class FakeWebSocket {
    static CLOSED = 3;
    static instances = [];
    constructor(url) { this.url = url; this.readyState = 0; FakeWebSocket.instances.push(this); }
    close() { this.readyState = FakeWebSocket.CLOSED; }
    emitClose(code) { this.readyState = FakeWebSocket.CLOSED; this.onclose?.({ code }); }
  }
  global.window = {
    location: { protocol: "https:", host: "tickety.example.com" },
    localStorage: { getItem: key => values.get(key) ?? null },
  };
  global.WebSocket = FakeWebSocket;
  global.setTimeout = (callback, delay) => { const timer = { callback, delay, cleared: false }; timers.push(timer); return timer; };
  global.clearTimeout = timer => { if (timer) timer.cleared = true; };
  try {
    const { createNotificationsWS } = loadWs();
    const client = createNotificationsWS("agent-a");
    client.connect();
    assert.match(FakeWebSocket.instances[0].url, /cursor=7$/);
    values.set("tickety.notifications.cursor.agent-a", "9");
    FakeWebSocket.instances[0].emitClose(1013);
    timers.at(-1).callback();
    assert.match(FakeWebSocket.instances[1].url, /cursor=9$/);
    client.disconnect();
  } finally {
    global.window = originalWindow;
    global.WebSocket = originalWebSocket;
    global.setTimeout = originalSetTimeout;
    global.clearTimeout = originalClearTimeout;
  }
});

test("one-shot analysis fails promptly when its websocket cannot start", () => {
  const source = read("components", "ticket", "AIThinkingStream.tsx");
  assert.match(source, /startHandshakeWatchdog/);
  assert.match(source, /30_000/);
  assert.match(source, /ws\.onClose/);
  assert.match(source, /ws\.onError/);
});

test("ticket analysis streams are fenced to the currently rendered ticket", () => {
  const source = read("components", "ticket", "AIThinkingStream.tsx");

  assert.match(source, /const streamGenerationRef = useRef\(0\)/);
  assert.match(source, /useLayoutEffect\(\(\) => \{[\s\S]*streamGenerationRef\.current = generation[\s\S]*\}, \[ticketId\]\)/);
  assert.doesNotMatch(source, /if \(streamGenerationRef\.current !== generation\) return;/);
  assert.match(source, /component unmounts[\s\S]*streamGenerationRef\.current \+= 1;[\s\S]*wsRef\.current\?\.disconnect\(\)/);
  assert.match(source, /const isCurrentStream = \(\) => \([\s\S]*streamGenerationRef\.current === generation && wsRef\.current === ws/);
  assert.match(source, /ws\.onMessage\(\(data\) => \{\s*if \(!isCurrentStream\(\)\) return;/);
  assert.match(source, /setResult\(null\);/);
});

test("ticket action drafts reset only when the ticket identity changes", () => {
  const source = read("app", "tickets", "[id]", "page.tsx");

  assert.match(source, /setComment\(""\);/);
  assert.match(source, /setIsPrivate\(false\);/);
  assert.match(source, /setSaveNotice\(null\);/);
  assert.match(source, /setCommentNotice\(null\);/);
  assert.match(source, /\}, \[ticket\.id\]\);/);
});

test("events from a disconnected socket cannot affect its replacement", () => {
  const originalWebSocket = global.WebSocket;
  const originalSetTimeout = global.setTimeout;
  const originalClearTimeout = global.clearTimeout;
  const timers = [];
  class FakeWebSocket {
    static CLOSED = 3;
    static instances = [];
    constructor() {
      this.readyState = 0;
      FakeWebSocket.instances.push(this);
    }
    close() { this.readyState = FakeWebSocket.CLOSED; }
  }
  global.WebSocket = FakeWebSocket;
  global.setTimeout = (callback, delay) => {
    const timer = { callback, delay, cleared: false };
    timers.push(timer);
    return timer;
  };
  global.clearTimeout = (timer) => { if (timer) timer.cleared = true; };
  try {
    const { WSClient } = loadWs();
    const client = new WSClient("/ws/notifications");
    const messages = [];
    const closes = [];
    const errors = [];
    client.onMessage((message) => messages.push(message));
    client.onClose((event) => closes.push(event));
    client.onError((event) => errors.push(event));
    client.connect();
    const oldSocket = FakeWebSocket.instances.at(-1);
    client.disconnect();
    client.connect();
    const currentSocket = FakeWebSocket.instances.at(-1);
    currentSocket.onopen();
    const currentStableTimer = timers.at(-1);

    // Browser events can already be queued when disconnect() closes a socket.
    oldSocket.onopen();
    oldSocket.onmessage({ data: '{"stale":true}' });
    oldSocket.onerror({ type: "error" });
    oldSocket.onclose({ code: 4401 });
    assert.deepEqual(messages, []);
    assert.deepEqual(closes, []);
    assert.deepEqual(errors, []);
    assert.equal(currentStableTimer.cleared, false);
    assert.equal(timers.length, 1);

    currentSocket.onmessage({ data: '{"fresh":true}' });
    assert.deepEqual(messages, [{ fresh: true }]);
    currentSocket.readyState = FakeWebSocket.CLOSED;
    currentSocket.onclose({ code: 1006 });
    assert.equal(closes.length, 1);
    assert.equal(currentStableTimer.cleared, true);
    assert.ok(timers.at(-1).delay >= 3_000 && timers.at(-1).delay <= 3_600);
    client.disconnect();
  } finally {
    global.WebSocket = originalWebSocket;
    global.setTimeout = originalSetTimeout;
    global.clearTimeout = originalClearTimeout;
  }
});
