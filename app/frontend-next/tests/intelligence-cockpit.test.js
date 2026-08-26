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
  const assurance = page.indexOf('data-intelligence-section="service-assurance"');
  const capacity = page.indexOf('data-intelligence-section="team-capacity"');
  const patterns = page.indexOf('data-intelligence-section="demand-patterns"');
  const automation = page.indexOf('data-intelligence-section="automation-discovery"');

  assert.ok(posture >= 0, "operational posture is present");
  assert.ok(attention > posture, "command queue follows posture");
  assert.ok(ageFlow > attention, "age and flow support the command queue");
  assert.ok(stale > ageFlow, "stale backlog is separated from live work");
  assert.ok(assurance > stale, "service assurance follows the command queue and hygiene context");
  assert.ok(capacity > assurance, "team capacity follows live service assurance");
  assert.ok(patterns > capacity, "patterns are supporting context, not the lead");
  assert.ok(automation > patterns, "one-time automation discovery is separated from live operations");
  assert.match(page, /eyebrow="Tickety Operations"/);
  assert.match(page, /title="OPS Tower"/);
  assert.match(page, /Command the Queue\. The intelligence behind every ticket\./);
  assert.match(page, /A decision-first view of current service risk, queue health, team capacity, and emerging demand\. Legacy records are isolated from live operational signals\./);
  assert.match(page, /Powered by CommandIQ\./);
  assert.doesNotMatch(page, /Helpdesk Command IQ|PulseIQ|ControlIQ/);
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
  assert.match(page, /api\.getIntelServiceQuality\(windowDays\)/);
  assert.match(page, /api\.getIntelSlaMonitoring\(windowDays\)/);
  assert.match(page, /api\.getIntelHealthForWindow\(activeReporter, windowDays\)/);
  assert.match(page, /Auto-refreshes every 30 seconds/);
  assert.match(page, /Import time never makes a legacy ticket look current/);

  for (const endpoint of ["overview", "service-quality", "sla-monitoring", "alerts", "prioritize", "sla", "trends", "systemic", "workload", "health"]) {
    assert.match(api, new RegExp(`intelligence/${endpoint}[\\s\\S]{0,240}window_days`), `${endpoint} supports an operational window`);
  }
});

test("service assurance exposes the requested human-review guardrails", () => {
  for (const label of [
    "Routing guardrail",
    "Level 0–3 alignment",
    "Customer friction",
    "Clarification needed",
    "SLA breach monitoring",
  ]) {
    assert.match(page, new RegExp(label));
  }
  assert.match(page, /Advisory guardrail — no automatic routing/);
  assert.match(page, /These signals never reassign, reprioritize, or reply to a ticket/);
  assert.match(page, /Freshservice does not currently define assigned tiers/);
  assert.match(page, /Approaching \(/);
  assert.match(page, /Breached \(/);
  assert.match(types, /export interface ServiceQualityResponse/);
  assert.match(types, /export interface SlaMonitoringResponse/);
  assert.match(api, /getIntelServiceQuality/);
  assert.match(api, /getIntelSlaMonitoring/);
});

test("cockpit exception counts open bounded ticket evidence", () => {
  assert.match(page, /function TicketEvidenceDialog/);
  assert.match(page, /Returned evidence is bounded/);
  assert.match(page, /View tickets/);
  assert.match(page, /function SlaCountButton/);
  assert.match(page, /Breached tickets by assignee/);
  assert.match(page, /groupSlaBreachesByAssignee\(data\.by_assignee\)/);
  assert.match(page, /item\.assignee_source === agent\.source && item\.assignee_id === agent\.user_id/);
  assert.match(page, /breachSummary\?\.breached_ticket_count/);
  assert.match(page, /getIntelSlaAssigneeEvidence/);
  assert.match(page, /result\.scope\.truncated/);
  assert.match(page, /Assignee scope is sampled/);
  assert.match(page, /SLA breach indicators unavailable/);
  assert.match(page, /Missing breach links do not mean an agent has zero breaches/);
  assert.match(page, /data\.unassigned_evidence\.items/);
  assert.match(page, /View \{cluster\.ticket_ids\.length\} evidence ticket/);
  assert.match(types, /assignee_id: string \| null/);
  assert.match(types, /assignee_name: string \| null/);
  assert.match(types, /assignee_source: "provider" \| "tickety" \| null/);
  assert.match(types, /by_assignee: SlaAssigneeBreachSummary\[\]/);
  assert.match(types, /export interface SlaAssigneeEvidenceResponse/);
  assert.match(types, /unassigned_evidence:/);
  assert.match(api, /sla-monitoring\/assignee-evidence/);
});

test("Level Zero study is persisted, deliberate, and outside live refresh", () => {
  assert.match(page, /Level Zero opportunity study/);
  assert.match(page, /never rerun automatically/);
  assert.match(page, /staleTime: Infinity/);
  assert.match(page, /refetchOnWindowFocus: false/);
  assert.match(page, /Run new snapshot/);
  assert.match(page, /Complete, unsampled review/);
  assert.match(api, /getLevelZeroStudy/);
  assert.match(api, /runLevelZeroStudy/);
  assert.match(types, /method: "complete_unsampled_rule_assessment"/);
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
