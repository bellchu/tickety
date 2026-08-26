const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const page = fs.readFileSync(path.join(__dirname, "..", "app", "routing", "page.tsx"), "utf8");
const api = fs.readFileSync(path.join(__dirname, "..", "lib", "api.ts"), "utf8");
const settings = fs.readFileSync(path.join(__dirname, "..", "app", "settings", "page.tsx"), "utf8");
const navigation = fs.readFileSync(path.join(__dirname, "..", "lib", "navigation.ts"), "utf8");

test("routing workspace is protected and keeps provider catalog mapping advisory", () => {
  assert.match(page, /canAccessProtectedIntelligence/);
  assert.match(page, /catalog mapping pending/i);
  assert.match(page, /does not apply provider group mappings/i);
  assert.doesNotMatch(page, /applyCatalogMapping|writeProviderGroup/);
});

test("routing workspace supports local multi-team agent mapping", () => {
  assert.match(page, /data-routing-section="agent-team-mappings"/);
  assert.match(page, /resolver_groups/);
  assert.match(page, /Edit teams/);
  assert.match(api, /\/admin\/agent-team-mappings\/\$\{encodeURIComponent\(userId\)\}/);
  assert.match(api, /expected_resolver_groups/);
});

test("structured rules are supervisor-safe and preserve the core policy", () => {
  assert.match(page, /Structured routing rules/);
  assert.match(page, /core evidence order, output schema, confidence limits, and trust boundary are protected/i);
  assert.match(page, /Add at least one match condition/);
  assert.match(api, /"\/admin\/routing-rules"/);
  assert.match(api, /expected_version/);
});

test("auto-triage remains available from the consolidated workspace", () => {
  assert.match(page, /Auto-triage/);
  assert.match(api, /"\/admin\/routing-triage\/automation"/);
  assert.match(api, /\/admin\/sync\/triage-all/);
  assert.match(settings, /href="\/routing"/);
  assert.doesNotMatch(settings, /label="Triage All Untriaged"/);
  assert.doesNotMatch(settings, /key: "AUTO_TRIAGE_ENABLED"/);
  assert.doesNotMatch(settings, /key: "AUTO_ROUTE_ENABLED"/);
  assert.match(navigation, /href: "\/routing",\s*label: "Routing & triage"/);
});
