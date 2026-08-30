const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const page = fs.readFileSync(path.join(root, "components", "settings", "AIRoutingSettings.tsx"), "utf8");
const api = fs.readFileSync(path.join(root, "lib", "api.ts"), "utf8");
const types = fs.readFileSync(path.join(root, "lib", "types.ts"), "utf8");

test("Routing & triage exposes read-only resolver mapping recommendations", () => {
  assert.match(page, /data-routing-section="catalog-mapping-pending"/);
  assert.match(page, /Recommendation only · catalog mapping pending/);
  assert.match(page, /does not apply provider group mappings from this view/);
  assert.match(page, /No recommendation is ready/);
  assert.match(page, /More trusted ticket history and provider membership evidence are needed/);
  assert.doesNotMatch(page, /Apply mapping|Save mapping|Create mapping/);
});

test("catalog recommendations use their fixed read-only endpoint", () => {
  assert.match(api, /getRoutingCatalogRecommendations: \(\) =>/);
  assert.match(api, /fetchAPI<import\("\.\/types"\)\.RoutingCatalogRecommendationsResponse>\(\s*"\/admin\/routing-catalog\/recommendations"\s*\)/);
  assert.doesNotMatch(api, /routing-catalog\/recommendations\?/);
  assert.match(page, /queryKey: \["routing", "catalog-recommendations"\]/);
  assert.match(page, /queryFn: api\.getRoutingCatalogRecommendations/);
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
  assert.match(page, /item\.evidence_ticket_count/);
  assert.match(page, /item\.distinct_agent_count/);
  assert.match(page, /item\.confidence/);
  assert.match(page, /item\.provider_group_name/);
  assert.match(page, /item\.scope\.binding_id/);
  assert.match(page, /item\.scope\.workspace_id/);
});
