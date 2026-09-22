const { loadPureTs } = require("./helpers/load-pure-ts");
const assert = require("node:assert/strict");
const test = require("node:test");

const {
  parseNotificationCursor,
  readNotificationCursor,
  rememberNotificationCursor,
  clearNotificationCursor,
} = loadPureTs("notification-cursor.ts");

test("notification replay cursors are bounded, monotonic, and user scoped", () => {
  const originalWindow = global.window;
  const data = new Map();
  global.window = {
    localStorage: {
      getItem: key => data.get(key) ?? null,
      setItem: (key, value) => data.set(key, value),
      removeItem: key => data.delete(key),
    },
  };
  try {
    for (const value of [null, "", "-1", "01", "1.1", "9007199254740992"]) {
      assert.equal(parseNotificationCursor(value), 0);
    }
    assert.equal(parseNotificationCursor("42"), 42);
    rememberNotificationCursor("agent-a", 11);
    rememberNotificationCursor("agent-a", 10);
    rememberNotificationCursor("agent-b", 4);
    assert.equal(readNotificationCursor("agent-a"), 11);
    assert.equal(readNotificationCursor("agent-b"), 4);
    clearNotificationCursor("agent-a");
    assert.equal(readNotificationCursor("agent-a"), 0);
    assert.equal(readNotificationCursor("agent-b"), 4, "logout cleanup is user scoped");
  } finally {
    global.window = originalWindow;
  }
});
