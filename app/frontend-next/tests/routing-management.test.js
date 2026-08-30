const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const page = fs.readFileSync(path.join(__dirname, "..", "components", "settings", "AIRoutingSettings.tsx"), "utf8");
const routingRoute = fs.readFileSync(path.join(__dirname, "..", "app", "routing", "page.tsx"), "utf8");
const api = fs.readFileSync(path.join(__dirname, "..", "lib", "api.ts"), "utf8");
const settings = fs.readFileSync(path.join(__dirname, "..", "app", "settings", "page.tsx"), "utf8");
const navigation = fs.readFileSync(path.join(__dirname, "..", "lib", "navigation.ts"), "utf8");

test("routing page preserves role-aware access and keeps provider catalog mapping advisory", () => {
  assert.match(settings, /canAccessAdministration/);
  assert.match(settings, /canAccessProtectedIntelligence/);
  assert.match(settings, /DelegatedAISettingsState/);
  assert.doesNotMatch(settings, /<AIRoutingSettings \/>/);
  assert.match(routingRoute, /<AIRoutingSettings \/>/);
  assert.match(page, /const canAccessRouting = canAccessProtectedIntelligence\(authQuery\.data\)/);
  assert.match(page, /enabled: canAccessRouting/);
  assert.match(page, /if \(!canAccessRouting\)/);
  assert.match(page, /catalog mapping pending/i);
  assert.match(page, /does not apply provider group mappings/i);
  assert.doesNotMatch(page, /applyCatalogMapping|writeProviderGroup/);
});

test("routing workspace supports guarded unified people mapping with a legacy fallback", () => {
  assert.match(page, /directory_people_read_enabled/);
  assert.match(page, /directoryEnabled \? "directory-people" : "agent-team-mappings"/);
  assert.match(page, /Freshservice requester/);
  assert.match(page, /Remote people remain read-only and cannot sign in/);
  assert.match(page, /resolver_groups/);
  assert.match(page, /Edit teams/);
  assert.match(page, /sourceType: "agent"/);
  assert.match(page, /Recommendations needing review/);
  assert.match(page, /Browse all active agents/);
  assert.match(page, /Provider agent ID/);
  assert.match(page, /Shared reply address/);
  assert.match(page, /<details/);
  assert.doesNotMatch(page, /active directory people/);
  assert.match(api, /\/admin\/directory-people/);
  assert.match(api, /getDirectoryPerson/);
  assert.match(api, /updateDirectoryPersonTeams/);
  assert.match(api, /expected_version/);
  assert.match(api, /\/admin\/agent-team-mappings\/\$\{encodeURIComponent\(userId\)\}/);
  assert.match(api, /expected_resolver_groups/);
});

test("agent mapping recommendations stay advisory and require an explicit admin save", () => {
  assert.match(api, /getAgentTeamMappingRecommendations/);
  assert.match(api, /\/admin\/agent-team-mapping-recommendations\?window_days=/);
  assert.match(page, /queryKey: \["routing", "agent-team-mapping-recommendations", recommendationWindowDays\]/);
  assert.match(page, /trusted routed ticket history/i);
  assert.match(page, /History recommendation/);
  assert.match(page, /conservative confidence/);
  assert.match(page, /Administrator approval required/);
  assert.match(page, /Review recommendation/);
  assert.match(page, /Saving is still an explicit administrator decision/);
  assert.match(page, /Recommendation evidence window in days/);
  assert.match(page, /recommendationWindowDraft >= 7 && recommendationWindowDraft <= 365/);
  assert.match(page, /changing this window does not call the AI provider or consume tokens/);
  assert.doesNotMatch(page, /autoApplyRecommendation|applyRecommendationAutomatically/);
});

test("structured rules preserve the core policy", () => {
  assert.match(page, /Structured routing rules/);
  assert.match(page, /core evidence order, output schema, confidence limits, and trust boundary are protected/i);
  assert.match(page, /Add at least one match condition/);
  assert.match(api, /"\/admin\/routing-rules"/);
  assert.match(api, /expected_version/);
});

test("automatic AI admission is explicit, resumable, and separate from historical batches", () => {
  assert.match(page, /api\.getSyncStatus/);
  assert.match(page, /api\.enableAutomaticAI/);
  assert.match(page, /api\.pauseAutomaticAI/);
  assert.match(page, /Start automatic AI/);
  assert.match(page, /latest four weeks will enter AI from newest to oldest/i);
  assert.match(page, /Older tickets remain manual/i);
  assert.match(api, /\/admin\/sync\/automatic-ai\/enable/);
  assert.match(api, /\/admin\/sync\/automatic-ai\/pause/);
});

test("global AI controls stay in settings while operational routing is consolidated on its own page", () => {
  assert.match(settings, /key: "AUTO_TRIAGE_ENABLED"/);
  assert.match(settings, /key: "AUTO_SUMMARIZE_ENABLED"/);
  assert.match(settings, /key: "AUTO_ROUTE_ENABLED"/);
  assert.match(settings, /key: "AUTO_RESOLVE_ENABLED"/);
  assert.match(settings, /key: "AUTO_SYSTEMIC_ENABLED"/);
  assert.match(api, /"\/admin\/routing-triage\/automation"/);
  assert.match(api, /\/admin\/sync\/triage-all/);
  assert.doesNotMatch(page, /updateRoutingTriageAutomation/);
  assert.match(settings, /id="settings-ai-maintenance"/);
  assert.match(settings, /label="Repair AI Gaps"/);
  assert.doesNotMatch(settings, /"settings-routing": "ai"/);
  assert.match(settings, /"settings-system": "ai"/);
  assert.match(settings, /href="\/routing"/);
  assert.doesNotMatch(settings, /id: "system", label: "System"/);
  assert.doesNotMatch(routingRoute, /redirect/);
  assert.match(routingRoute, /title="Routing & triage"/);
  assert.match(navigation, /href: "\/routing"/);
});
