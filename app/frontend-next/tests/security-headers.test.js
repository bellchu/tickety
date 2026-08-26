const assert = require("node:assert/strict");
const test = require("node:test");

const nextConfig = require("../next.config.js");

function asMap(headers) {
  return new Map(headers.map(({ key, value }) => [key.toLowerCase(), value]));
}

test("production routes receive a strict browser security baseline", async () => {
  const previous = process.env.NODE_ENV;
  process.env.NODE_ENV = "production";
  try {
    const rules = await nextConfig.headers();
    assert.equal(nextConfig.poweredByHeader, false);
    assert.equal(rules.length, 1);
    assert.equal(rules[0].source, "/(.*)");
    const headers = asMap(rules[0].headers);

    assert.equal(
      headers.get("strict-transport-security"),
      "max-age=31536000; includeSubDomains",
    );
    assert.equal(headers.get("x-content-type-options"), "nosniff");
    assert.equal(headers.get("x-frame-options"), "DENY");
    assert.equal(
      headers.get("referrer-policy"),
      "strict-origin-when-cross-origin",
    );
    assert.match(headers.get("permissions-policy"), /camera=\(\)/);

    const policy = headers.get("content-security-policy");
    assert.match(policy, /default-src 'self'/);
    assert.match(policy, /object-src 'none'/);
    assert.match(policy, /frame-ancestors 'none'/);
    assert.match(policy, /connect-src 'self' wss:/);
    assert.doesNotMatch(policy, /unsafe-eval/);
    for (const value of headers.values()) assert.doesNotMatch(value, /[\r\n]/);
  } finally {
    if (previous === undefined) delete process.env.NODE_ENV;
    else process.env.NODE_ENV = previous;
  }
});

test("development CSP permits the evaluator required by Next development", async () => {
  const previous = process.env.NODE_ENV;
  process.env.NODE_ENV = "development";
  try {
    const rules = await nextConfig.headers();
    const policy = asMap(rules[0].headers).get("content-security-policy");
    assert.match(policy, /script-src 'self' 'unsafe-inline' 'unsafe-eval'/);
  } finally {
    if (previous === undefined) delete process.env.NODE_ENV;
    else process.env.NODE_ENV = previous;
  }
});
