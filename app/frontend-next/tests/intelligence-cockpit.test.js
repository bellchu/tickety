const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const page = fs.readFileSync(path.join(root, "components", "intelligence", "IntelligenceWorkspace.tsx"), "utf8");
const api = fs.readFileSync(path.join(root, "lib", "api.ts"), "utf8");
const types = fs.readFileSync(path.join(root, "lib", "types.ts"), "utf8");

test("OPS Tower is decision-first and routes deeper functions to focused pages", () => {
  const posture = page.indexOf('data-intelligence-section="operational-posture"');
  const attention = page.indexOf('data-intelligence-section="attention-queue"');
  const ageFlow = page.indexOf('data-intelligence-section="age-flow"');
  const stale = page.indexOf('data-intelligence-section="stale-backlog"');
  const assurance = page.indexOf('data-intelligence-section="service-assurance"');
  const capacity = page.indexOf('data-intelligence-section="team-capacity"');
  const patterns = page.indexOf('data-intelligence-section="demand-patterns"');
  const automation = page.indexOf('data-intelligence-section="automation-discovery"');

  assert.ok(posture >= 0, "operational posture is present");
  assert.ok(attention >= 0, "command queue is present on overview");
  assert.ok(ageFlow >= 0, "age and flow context is present on overview");
  assert.ok(stale >= 0, "stale backlog is isolated on overview");
  assert.ok(assurance >= 0, "service assurance has a focused view");
  assert.ok(capacity >= 0, "team capacity has a focused view");
  assert.ok(patterns >= 0, "demand patterns have a focused view");
  assert.ok(automation >= 0, "automation discovery has a focused view");
  assert.match(page, /<nav aria-label="OPS Tower workspaces" className="-mt-2 pb-1">/);
  assert.match(page, /grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5/);
  assert.match(page, /href: "\/intelligence\/service-assurance"/);
  assert.match(page, /href: "\/intelligence\/team-capacity"/);
  assert.match(page, /href: "\/intelligence\/demand-patterns"/);
  assert.match(page, /href: "\/intelligence\/automation-discovery"/);
  assert.doesNotMatch(page, /aria-label="Supporting intelligence views"/);
  assert.doesNotMatch(page, /<details data-intelligence-section=/);
  assert.match(page, /eyebrow="Tickety OPS Tower"/);
  assert.match(page, /title=\{view === "overview" \? "OPS Tower" : active\.label\}/);
  assert.match(page, /Command the Queue\. The intelligence behind every ticket\./);
  assert.match(page, /A decision-first view of current service risk and queue health\./);
  assert.match(page, /Powered by CommandIQ\./);
  assert.doesNotMatch(page, /Helpdesk Command IQ|PulseIQ|ControlIQ/);
  assert.match(page, /do not inflate current SLA, trend, workload, or systemic signals/);
  assert.match(page, /Review in All Tickets/);
  assert.match(page, /attention_queue\.slice\(0, 5\)/);
  assert.doesNotMatch(page, /attention_queue\.slice\(0, 10\)/);
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
  assert.match(page, /enabled: view === "overview"/);
  assert.match(page, /enabled: view === "service-assurance"/);
  assert.match(page, /enabled: view === "team-capacity"/);
  assert.match(page, /enabled: view === "demand-patterns"/);
  assert.match(page, /enabled: view === "service-assurance" \|\| view === "team-capacity"/);
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

test("demand patterns explain sparse evidence instead of rendering blank sections", () => {
  assert.match(page, />Categories</);
  assert.match(page, /No current trusted category classifications/);
  assert.match(page, /No current trusted sentiment classifications/);
  assert.match(page, /No recurring trusted pattern terms in this window/);
  assert.match(page, /Trusted pattern evidence covers/);
  assert.match(types, /pattern_evidence_tickets: number/);
});

test("duplicate provider display names retain visible provider identity", () => {
  assert.match(types, /provider: string \| null/);
  assert.match(types, /external_id: string \| null/);
  assert.match(page, /providerNameCounts/);
  assert.match(page, /duplicateProviderName/);
  assert.match(page, /agent\.external_id/);
  assert.match(page, /Freshservice/);
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

test("flow never presents an import-time fallback or a bare negative KPI", () => {
  assert.match(page, /label="Backlog change"/);
  assert.match(page, /formatBacklogChange/);
  assert.match(page, /Backlog change unavailable/);
  assert.match(page, /Net backlog change is withheld instead of showing a misleading number/);
  assert.match(page, /Resolved \(timed\)/);
  assert.doesNotMatch(page, /label="Net flow"/);
  assert.doesNotMatch(page, /function withSign/);
  assert.match(types, /net_change: number \| null/);
  assert.match(types, /measurement_complete: boolean/);
  assert.match(types, /missing_created_timestamps: number/);
  assert.match(types, /missing_resolved_timestamps: number/);
});

test("protected cockpit remains fail-closed before operational queries mount", () => {
  assert.match(page, /const canAccessIntelligence = canAccessProtectedIntelligence\(authQuery\.data\)/);
  assert.match(page, /if \(!canAccessIntelligence\)/);
  assert.match(page, /return <IntelligenceCockpit view=\{view\} \/>/);
  assert.ok(
    page.indexOf("if (!canAccessIntelligence)") < page.indexOf("return <IntelligenceCockpit view={view} />"),
    "access denial precedes cockpit mounting",
  );
});
