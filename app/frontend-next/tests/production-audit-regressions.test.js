const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");

test("admin status distinguishes effective API key auth from OAuth state", () => {
  const api = read("lib", "api.ts");
  const status = read("app", "settings", "status", "page.tsx");

  assert.match(api, /integration_connected: boolean/);
  assert.match(api, /auth_method: "oauth" \| "api_key" \| "none"/);
  assert.match(status, /oauth\?\.integration_connected/);
  assert.match(status, /Effective read-only authentication/);
  assert.doesNotMatch(status, /Server-side OAuth configuration and current connection state/);
});

test("reports and surveys preserve no-sample semantics and block incomplete delivery", () => {
  const reports = read("app", "reports", "page.tsx");
  const surveys = read("app", "surveys", "page.tsx");
  const types = read("lib", "types.ts");

  assert.match(types, /csat_proxy: number \| null/);
  assert.match(reports, /No responses/);
  assert.match(surveys, /Response rate[^\n]+No data/);
  assert.match(surveys, /Active survey template required/);
  assert.match(surveys, /Email delivery is not configured/);
  assert.match(surveys, /activeTemplates\.length === 0/);
  assert.match(surveys, /!emailConfigured/);
});

test("production portal exposes the configured Freshservice destination", () => {
  const api = read("lib", "api.ts");
  const portal = read("app", "portal", "page.tsx");

  assert.match(api, /getPortalConfig/);
  assert.match(portal, /Open Freshservice portal/);
  assert.match(portal, /rel="noopener noreferrer"/);
  assert.match(portal, /support administrator for the requester portal link/);
});

test("audited mobile and ranking presentation is explicit and non-wrapping", () => {
  const overview = read("app", "page.tsx");
  const settings = read("app", "settings", "page.tsx");

  assert.match(overview, /Equal scores retain the declared-priority queue order/);
  assert.match(overview, /inline-flex items-baseline gap-1 whitespace-nowrap/);
  assert.match(settings, /Swipe horizontally to see every settings section/);
  assert.match(settings, /No local ticket statuses configured/);
  assert.match(settings, /Provider-imported priority values can still be displayed/);
});

test("every top-level production module has route-specific metadata", () => {
  const routes = [
    "agent", "agents", "assets", "changes", "email", "intelligence",
    "knowledge", "leaderboard", "login", "portal", "problems", "profile",
    "reports", "routing", "services", "settings", "surveys", "tickets", "time",
  ];

  for (const route of routes) {
    const source = read("app", route, route === "agent" ? "page.tsx" : "layout.tsx");
    assert.match(source, /export const metadata: Metadata/);
    assert.match(source, /title:/);
  }
  assert.match(read("app", "settings", "status", "layout.tsx"), /title: "Admin status"/);
});
