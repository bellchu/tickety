const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function loadRealtimeValidation() {
  const filename = path.join(__dirname, "..", "lib", "realtime-validation.ts");
  const source = fs.readFileSync(filename, "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
    fileName: filename,
  }).outputText;
  const loaded = { exports: {} };
  const compile = new Function("exports", "module", output);
  compile(loaded.exports, loaded);
  return loaded.exports;
}

const {
  isPointsNotification,
  isTicketAnalysisResult,
  isTriageProgressMessage,
  triageWatchdogDelayMs,
} = loadRealtimeValidation();

function analysis(overrides = {}) {
  return {
    ticket_id: "ticket-1",
    triage: {
      ticket_id: "ticket-1", sentiment: "Neutral", category: "Other", priority: "P3",
      mood: "neutral", complexity: 1, action: "respond", recommended_team: "Application Support", reasoning: "Review logs",
      suggested_response: null, escalation_risk: 10,
    },
    summary: null,
    route: {
      recommended_user_id: "user-1", recommended_name: "User", reasoning: "Best match", tier_needed: 1,
      candidates: [{ user_id: "user-1", name: "User", tier: 1, impact_points: 4, momentum: 2, score: 18, tier_ok: true }],
      total_users: 1, analyzed_users: 1, candidate_pool_truncated: false,
    },
    recommended_solution: {
      ticket_id: "ticket-1",
      plan: {
        root_cause_hypothesis: "Configuration", resolution_steps: ["Correct configuration"],
        confidence: "medium", estimated_effort: "low", escalation_advice: "Escalate if unresolved", preventive_note: "Document it",
      },
      cached: false,
    },
    documents_changed: 1,
    errors: [],
    cached: false,
    ...overrides,
  };
}

function notification(overrides = {}) {
  return {
    ticket_id: "ticket-1", ticket_subject: "Unable to sign in", user_id: "user-1", user_name: "User",
    points_earned: 10, new_total: 100, new_tier: 2, tier_promoted: true, new_momentum: 3,
    recognitions_unlocked: [{
      id: 1, user_id: "user-1", recognition_key: "first-resolution", unlocked_at: "2026-07-31T12:00:00Z",
      ticket_id: "ticket-1", display_name: "First resolution", description: "Resolved a ticket", icon: "award",
    }],
    ...overrides,
  };
}

test("triage messages require valid progress and complete result structures", () => {
  assert.equal(isTriageProgressMessage({
    type: "progress", timeout_seconds: 900,
    steps: [{ step: "triage", label: "Classifying", status: "active" }],
  }), true);
  assert.equal(isTriageProgressMessage({
    type: "progress", timeout_seconds: 900,
    steps: [
      { step: "triage", label: "Classifying", status: "done" },
      { step: "resolution", label: "Drafting resolution plan", status: "error" },
    ],
  }), true);
  assert.equal(isTriageProgressMessage({
    type: "progress", timeout_seconds: 900,
    steps: [{ step: "resolution", label: "Drafting resolution plan", status: "failed" }],
  }), false);
  assert.equal(isTriageProgressMessage(null), false);
  assert.equal(isTriageProgressMessage({ type: "progress", timeout_seconds: 900, steps: null }), false);
  assert.equal(isTicketAnalysisResult(analysis(), "ticket-1"), true);
  assert.equal(isTicketAnalysisResult(analysis({ ticket_id: "ticket-2" }), "ticket-1"), false);
  assert.equal(isTicketAnalysisResult(analysis({ triage: { ...analysis().triage, ticket_id: "ticket-2" } }), "ticket-1"), false);
  assert.equal(isTicketAnalysisResult(analysis({ route: {} }), "ticket-1"), false);
  assert.equal(isTicketAnalysisResult(analysis({ recommended_solution: { ticket_id: "ticket-1", plan: {}, cached: false } }), "ticket-1"), false);
});

test("notifications require all rendered fields and complete recognition records", () => {
  assert.equal(isPointsNotification(notification()), true);
  assert.equal(isPointsNotification(notification({ user_name: undefined })), false);
  assert.equal(isPointsNotification(notification({ recognitions_unlocked: [null] })), false);
  assert.equal(isPointsNotification(notification({ recognitions_unlocked: [{ id: 1 }] })), false);
});

test("watchdog uses bounded backend timeout plus a recovery margin", () => {
  assert.equal(triageWatchdogDelayMs(900), 930_000);
  assert.equal(triageWatchdogDelayMs(1), 150_000);
  assert.equal(triageWatchdogDelayMs(9_999), 3_630_000);
  assert.equal(triageWatchdogDelayMs(undefined), 930_000);
});
