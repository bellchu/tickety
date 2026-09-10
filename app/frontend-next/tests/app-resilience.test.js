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
  new Function("exports", "module", output)(loaded.exports, loaded);
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
    FakeWebSocket.instances.at(-1).emitClose(1006);
    assert.equal(timers.at(-1).delay, 3_000);
    timers.at(-1).callback();
    FakeWebSocket.instances.at(-1).emitClose(1006);
    assert.equal(timers.at(-1).delay, 6_000);
    transientClient.disconnect();
    assert.equal(timers.at(-1).cleared, true);
  } finally {
    global.window = originalWindow;
    global.WebSocket = originalWebSocket;
    global.setTimeout = originalSetTimeout;
    global.clearTimeout = originalClearTimeout;
    Math.random = originalRandom;
  }
});

test("one-shot analysis fails promptly when its websocket cannot start", () => {
  const source = read("components", "ticket", "AIThinkingStream.tsx");
  assert.match(source, /startHandshakeWatchdog/);
  assert.match(source, /30_000/);
  assert.match(source, /ws\.onClose/);
  assert.match(source, /ws\.onError/);
});
