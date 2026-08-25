const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const page = fs.readFileSync(path.join(root, "app", "intelligence", "page.tsx"), "utf8");
const api = fs.readFileSync(path.join(root, "lib", "api.ts"), "utf8");
const types = fs.readFileSync(path.join(root, "lib", "types.ts"), "utf8");

test("intelligence cockpit is decision-first and isolates backlog hygiene", () => {
  const posture = page.indexOf('data-intelligence-section="operational-posture"');
  const attention = page.indexOf('data-intelligence-section="attention-queue"');
  const ageFlow = page.indexOf('data-intelligence-section="age-flow"');
  const stale = page.indexOf('data-intelligence-section="stale-backlog"');
  const capacity = page.indexOf('data-intelligence-section="team-capacity"');
  const patterns = page.indexOf('data-intelligence-section="demand-patterns"');

  assert.ok(posture >= 0, "operational posture is present");
  assert.ok(attention > posture, "command queue follows posture");
  assert.ok(ageFlow > attention, "age and flow support the command queue");
  assert.ok(stale > ageFlow, "stale backlog is separated from live work");
  assert.ok(capacity > stale, "team capacity follows immediate work");
  assert.ok(patterns > capacity, "patterns are supporting context, not the lead");
  assert.match(page, /Legacy records are isolated from live operational signals/);
  assert.match(page, /do not inflate current SLA, trend, workload, or systemic signals/);
  assert.match(page, /Review in All Tickets/);
});

test("one bounded activity-window control scopes every cockpit query", () => {
  assert.match(page, /const WINDOWS = \[7, 30, 90\] as const/);
  assert.match(page, /useState<WindowDays>\(30\)/);
  assert.match(page, /api\.getIntelOverview\(windowDays\)/);
  assert.match(page, /api\.getIntelTrendsForWindow\(windowDays\)/);
  assert.match(page, /api\.getIntelWorkload\(windowDays\)/);
  assert.match(page, /api\.getIntelSystemicForWindow\(2, windowDays\)/);
  assert.match(page, /api\.getIntelHealthForWindow\(activeReporter, windowDays\)/);
  assert.match(page, /Auto-refreshes every 30 seconds/);
  assert.match(page, /Import time never makes a legacy ticket look current/);

  for (const endpoint of ["overview", "alerts", "prioritize", "sla", "trends", "systemic", "workload", "health"]) {
    assert.match(api, new RegExp(`intelligence/${endpoint}[\\s\\S]{0,240}window_days`), `${endpoint} supports an operational window`);
  }
});

test("cockpit contract exposes freshness, scope, posture, action, and stale evidence", () => {
  assert.match(types, /export interface IntelligenceOverviewResponse/);
  assert.match(types, /activity_basis: "provider_updated_at_or_created_at"/);
  assert.match(types, /excluded_stale_open_tickets: number/);
  assert.match(types, /attention_queue: IntelligenceAttentionTicket\[\]/);
  assert.match(types, /stale_backlog:/);
  assert.match(types, /latest_ticket_activity_at: string \| null/);
  assert.match(types, /target_source: "provider_due_at" \| "priority_policy"/);
});

test("protected cockpit remains fail-closed before operational queries mount", () => {
  assert.match(page, /const canAccessIntelligence = canAccessProtectedIntelligence\(authQuery\.data\)/);
  assert.match(page, /if \(!canAccessIntelligence\)/);
  assert.match(page, /return <IntelligenceCockpit \/>/);
  assert.ok(
    page.indexOf("if (!canAccessIntelligence)") < page.indexOf("return <IntelligenceCockpit />"),
    "access denial precedes cockpit mounting",
  );
});
