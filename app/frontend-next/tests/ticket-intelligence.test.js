const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function loadHelpers() {
  const filename = path.join(__dirname, "..", "lib", "ticket-intelligence.ts");
  const source = fs.readFileSync(filename, "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 },
    fileName: filename,
  }).outputText;
  const loaded = { exports: {} };
  new Function("exports", "module", output)(loaded.exports, loaded);
  return loaded.exports;
}

const { analysisLifecycleLabel, relatedStrength, routingLabel, sourceKindLabel } = loadHelpers();
const emptyAnalysis = {
  ai_status: null,
  ai_lease_expires_at: null,
  ai_next_attempt_at: null,
  ai_generated_at: null,
  ai_reasoning: null,
  summary: null,
};

test("analysis lifecycle renders every operational state without exposing raw status", () => {
  const now = Date.parse("2026-08-23T12:00:00Z");
  assert.equal(analysisLifecycleLabel(emptyAnalysis, now), "Not analyzed");
  assert.equal(analysisLifecycleLabel({ ...emptyAnalysis, ai_status: "queued" }, now), "Queued");
  assert.equal(analysisLifecycleLabel({ ...emptyAnalysis, ai_status: "queued", ai_next_attempt_at: "2026-08-23T12:01:00Z" }, now), "Retry scheduled");
  assert.equal(analysisLifecycleLabel({ ...emptyAnalysis, ai_status: "running", ai_lease_expires_at: "2026-08-23T12:01:00Z" }, now), "Analyzing");
  assert.equal(analysisLifecycleLabel({ ...emptyAnalysis, ai_status: "running", ai_lease_expires_at: "2026-08-23T11:59:00Z" }, now), "Needs refresh");
  assert.equal(analysisLifecycleLabel({ ...emptyAnalysis, ai_status: "completed" }, now), "Ready");
  assert.equal(analysisLifecycleLabel({ ...emptyAnalysis, ai_status: "partial" }, now), "Partial results");
  assert.equal(analysisLifecycleLabel({ ...emptyAnalysis, ai_status: "stale" }, now), "Needs refresh");
  assert.equal(analysisLifecycleLabel({ ...emptyAnalysis, ai_status: "failed" }, now), "Analysis failed");
  assert.equal(analysisLifecycleLabel({ ...emptyAnalysis, ai_status: "dead_letter" }, now), "Needs attention");
});

test("routing, source, and related labels preserve their derivation", () => {
  assert.equal(routingLabel({ recommended_team: "Network Operations", recommended_team_basis: "ai_category" }), "Recommended team - Network Operations");
  assert.equal(routingLabel({ recommended_team: "Service Desk", recommended_team_basis: "fallback" }), "Default route - Service Desk");
  assert.equal(sourceKindLabel({ external_source: "freshservice", ticket_type: "service_request" }), "Freshservice Service Request");
  assert.equal(relatedStrength(0.9, "vector"), "Strong match");
  assert.equal(relatedStrength(0.6, "vector"), "Related");
  assert.equal(relatedStrength(0.3, "vector"), "Possible");
  assert.equal(relatedStrength(1, "keyword"), "Keyword");
});
