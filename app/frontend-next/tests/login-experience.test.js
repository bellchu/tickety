const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const source = fs.readFileSync(
  path.join(__dirname, "..", "app", "login", "page.tsx"),
  "utf8",
);

test("login keeps one visible primary heading across responsive layouts", () => {
  assert.equal((source.match(/<h1/g) || []).length, 1);
  assert.match(source, /<h1[^>]*>Welcome back<\/h1>/);
  assert.match(source, /<h2[^>]*>\s*Move support work forward with confidence/);
});

test("login distinguishes credential, rate-limit, and availability failures", () => {
  assert.match(source, /cause instanceof APIError && cause\.status === 401/);
  assert.match(source, /cause instanceof APIError && cause\.status === 429/);
  assert.match(source, /sign-in service is temporarily unavailable/);
});
