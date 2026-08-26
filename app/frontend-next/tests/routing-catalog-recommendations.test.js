const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const page = fs.readFileSync(path.join(root, "app", "intelligence", "page.tsx"), "utf8");
const api = fs.readFileSync(path.join(root, "lib", "api.ts"), "utf8");
const types = fs.readFileSync(path.join(root, "lib", "types.ts"), "utf8");

test("protected intelligence exposes read-only resolver mapping recommendations", () => {
  assert.match(page, /data-intelligence-section="routing-catalog-recommendations"/);
  assert.match(page, /Advisory only — no mapping was made/);
  assert.match(page, /Current synchronized ticket assignments are correlated with provider group membership/);
  assert.doesNotMatch(page, /Completed ticket assignments/);
  assert.match(page, /These recommendations do not modify ticket routing, provider groups, or application settings/);
  assert.match(page, /No fallback mapping was guessed/);
  assert.match(page, /No evidence-backed mappings to recommend/);
  assert.match(page, /Provider group membership is not ready/);
  assert.match(page, /Complete the Freshservice directory sync/);
  assert.match(page, /Resolver mapping recommendations unavailable/);
  assert.match(page, /Refresh failed — prior snapshot retained/);
  assert.doesNotMatch(page, /Apply mapping|Save mapping|Create mapping/);
});

test("recommendations use the fixed read-only admin endpoint without an activity-window query", () => {
  assert.match(api, /getRoutingCatalogRecommendations: \(\) =>/);
  assert.match(api, /fetchAPI<import\("\.\/types"\)\.RoutingCatalogRecommendationsResponse>\(\s*"\/admin\/routing-catalog\/recommendations"\s*\)/);
  assert.doesNotMatch(api, /routing-catalog\/recommendations\?/);
  assert.match(page, /queryKey: \["intelligence", "routing-catalog-recommendations"\]/);
  assert.match(page, /queryFn: api\.getRoutingCatalogRecommendations/);
  assert.match(page, /snapshot is independent of the operational activity-window control/);
});

test("recommendation contract includes provider identity, evidence, and unmapped codes", () => {
  assert.match(types, /export interface RoutingCatalogScope/);
  assert.match(types, /workspace_id: string \| null/);
  assert.match(types, /export interface RoutingCatalogRecommendation/);
  assert.match(types, /provider_group_id: string/);
  assert.match(types, /evidence_coverage: number/);
  assert.match(types, /export interface RoutingCatalogScopedGap/);
  assert.match(types, /export interface RoutingCatalogRecommendationsResponse/);
  assert.match(types, /recommendations: RoutingCatalogRecommendation\[\]/);
  assert.match(types, /scoped_gaps: RoutingCatalogScopedGap\[\]/);
  assert.match(types, /unmapped_codes: ResolverGroup\[\]/);
  assert.match(types, /history_truncated: boolean/);
  assert.match(page, /recommendation\.evidence_ticket_count\.toLocaleString\(\)/);
  assert.match(page, /recommendation\.distinct_agent_count\.toLocaleString\(\)/);
  assert.match(page, /routingCatalogPercent\(recommendation\.group_share\)/);
  assert.match(page, /routingCatalogPercent\(recommendation\.evidence_coverage\)/);
  assert.match(page, /data\.coverage\.history_truncated/);
  assert.match(page, /data\.scoped_gaps\.length/);
  assert.match(page, /JSON\.stringify\(\[recommendation\.resolver_code, scope\.binding_id, scope\.provider, scope\.workspace_id, recommendation\.provider_group_id\]\)/);
});
