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
  const dateTime = loadTypeScriptModule(path.join(__dirname, "..", "lib", "date-time.ts"));
  new Function("require", "exports", "module", output)(
    (specifier) => specifier === "@/lib/date-time" ? dateTime : require(specifier),
    loaded.exports,
    loaded,
  );
  return loaded.exports;
}

function loadTypeScriptModule(filename) {
  const output = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 },
    fileName: filename,
  }).outputText;
  const loaded = { exports: {} };
  new Function("exports", "module", output)(loaded.exports, loaded);
  return loaded.exports;
}

const {
  analysisLifecycleLabel,
  hasTrustedPersistedTicketAnalysis,
  relatedStrength,
  routingLabel,
  sourceKindLabel,
  ticketSentimentPresentation,
  ticketSignalRatings,
} = loadHelpers();
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
  assert.equal(analysisLifecycleLabel({ ...emptyAnalysis, ai_status: "queued", ai_next_attempt_at: "2026-08-23T12:01:00" }, now), "Retry scheduled");
  assert.equal(analysisLifecycleLabel({ ...emptyAnalysis, ai_status: "running", ai_lease_expires_at: "2026-08-23T12:01:00Z" }, now), "Analyzing");
  assert.equal(analysisLifecycleLabel({ ...emptyAnalysis, ai_status: "running", ai_lease_expires_at: "2026-08-23T11:59:00Z" }, now), "Needs refresh");
  assert.equal(analysisLifecycleLabel({ ...emptyAnalysis, ai_status: "completed" }, now), "Ready");
  assert.equal(analysisLifecycleLabel({ ...emptyAnalysis, ai_status: "partial" }, now), "Partial results");
  assert.equal(analysisLifecycleLabel({ ...emptyAnalysis, ai_status: "stale" }, now), "Needs refresh");
  assert.equal(analysisLifecycleLabel({ ...emptyAnalysis, ai_status: "failed" }, now), "Analysis failed");
  assert.equal(analysisLifecycleLabel({ ...emptyAnalysis, ai_status: "dead_letter" }, now), "Needs attention");
});

test("routing, source, and related labels preserve their derivation", () => {
  assert.equal(routingLabel({ recommended_team: "Freshservice group 2000241178", recommended_team_basis: "source_group", routing_catalog_validated: false }), "AI team analysis pending");
  assert.equal(routingLabel({ recommended_team: "INFRASTRUCTURE_OPERATIONS", recommended_team_basis: "ai_team", routing_catalog_validated: false }), "AI resolver recommendation - INFRASTRUCTURE_OPERATIONS (advisory; catalog mapping pending)");
  assert.equal(routingLabel({ recommended_team: "INFRASTRUCTURE_OPERATIONS", recommended_team_basis: "ai_team", routing_catalog_validated: true }), "AI resolver recommendation - INFRASTRUCTURE_OPERATIONS");
  assert.equal(routingLabel({ recommended_team: "Network Operations", recommended_team_basis: "ai_category", routing_catalog_validated: false }), "Suggested team - Network Operations (catalog validation pending)");
  assert.equal(routingLabel({ recommended_team: "Application Support", recommended_team_basis: "source_category", routing_catalog_validated: false }), "Suggested team - Application Support (Freshservice category)");
  assert.equal(routingLabel({ recommended_team: "No active routing", recommended_team_basis: "not_applicable", routing_catalog_validated: false }), "No active route - ticket closed");
  assert.equal(routingLabel({ recommended_team: "Unrouted / Review", recommended_team_basis: "unrouted_review", routing_catalog_validated: false }), "Unrouted - review required");
  assert.equal(sourceKindLabel({ external_source: "freshservice", ticket_type: "service_request" }), "Freshservice Service Request");
  assert.equal(relatedStrength(0.9, "vector"), "Strong match");
  assert.equal(relatedStrength(0.6, "vector"), "Related");
  assert.equal(relatedStrength(0.3, "vector"), "Possible");
  assert.equal(relatedStrength(1, "keyword"), "Keyword");
});

function signalTicket(overrides = {}) {
  return {
    id: "ticket-1",
    urgency: null,
    priority: "P3",
    ai_suggested_priority: null,
    sentiment: null,
    mood: null,
    complexity: 1,
    escalation_risk: 0,
    ai_status: null,
    ai_reasoning: null,
    ...overrides,
  };
}

function freshAnalysis(overrides = {}) {
  return {
    ticket_id: "ticket-1",
    triage: {
      ticket_id: "ticket-1",
      sentiment: "Moderate",
      category: "Other",
      priority: "P2",
      mood: "concerned",
      complexity: 3,
      action: "respond",
      recommended_team: "Application Support",
      reasoning: "scope: single user; contained impact",
      suggested_response: null,
      escalation_risk: 41,
      ...overrides,
    },
    summary: null,
    route: null,
    recommended_solution: null,
    documents_changed: 0,
    errors: [],
    cached: false,
  };
}

function byKey(ratings, key) {
  return ratings.find((rating) => rating.key === key);
}

test("content signals keep a stable four-item star order and do not trust reported priority as analysis", () => {
  const ratings = ticketSignalRatings(signalTicket());
  assert.deepEqual(ratings.map((rating) => rating.key), [
    "content-priority",
    "business-impact",
    "complexity",
    "escalation-risk",
  ]);
  assert.equal(byKey(ratings, "content-priority").score, null);
  assert.equal(byKey(ratings, "content-priority").sourceLabel, "AI-assessed");
  assert.match(byKey(ratings, "content-priority").detail, /reported priority is P3/);
  for (const key of ["business-impact", "complexity", "escalation-risk"]) {
    assert.equal(byKey(ratings, key).score, null);
    assert.equal(byKey(ratings, key).detail, "Awaiting a completed AI analysis");
  }
});

test("content priority uses trusted AI P1-P4 values and never lets reported urgency override them", () => {
  const cases = [
    ["P1", "P4", 5],
    [" p2 ", "P4", 4],
    ["p3", "P1", 3],
    ["P4", "P1", 2],
  ];
  for (const [ai_suggested_priority, priority, expected] of cases) {
    const rating = byKey(ticketSignalRatings(signalTicket({
      ai_status: "completed",
      ai_reasoning: "scope and impact evidence",
      ai_suggested_priority,
      priority,
    })), "content-priority");
    assert.equal(rating.score, expected);
    assert.match(rating.detail, new RegExp(`Content supports ${ai_suggested_priority.trim().toUpperCase()}`));
  }
  assert.equal(byKey(ticketSignalRatings(signalTicket({
    ai_status: "completed",
    ai_reasoning: "evidence",
    ai_suggested_priority: "urgent",
    priority: "P1",
  })), "content-priority").score, null);
  assert.equal(cases.some(([, , score]) => score === 1), false);
});

test("persisted AI ratings require a completed-compatible status and nonblank reasoning", () => {
  for (const status of ["completed", "triage_completed", "partial", " TRIAGE COMPLETED "]) {
    assert.equal(hasTrustedPersistedTicketAnalysis({ ai_status: status, ai_reasoning: "evidence" }), true);
  }
  for (const status of [null, "stale", "legacy_stale", "provenance_unknown", "queued", "running", "failed", "dead_letter", "unknown"]) {
    assert.equal(hasTrustedPersistedTicketAnalysis({ ai_status: status, ai_reasoning: "evidence" }), false);
  }
  assert.equal(hasTrustedPersistedTicketAnalysis({ ai_status: "completed", ai_reasoning: "   " }), false);
  assert.equal(hasTrustedPersistedTicketAnalysis({
    ai_status: "queued",
    ai_reasoning: "evidence",
    ai_requested_artifacts: "summary",
  }), true);
  assert.equal(hasTrustedPersistedTicketAnalysis({
    ai_status: "dead_letter",
    ai_reasoning: "evidence",
    ai_requested_artifacts: "resolution",
  }), true);
  assert.equal(hasTrustedPersistedTicketAnalysis({
    ai_status: "queued",
    ai_reasoning: "old evidence",
    ai_requested_artifacts: "triage",
  }), false);
});

test("business impact and subject sentiment normalize their complete taxonomies", () => {
  const impacts = [
    ["Business Critical", 5],
    [" high_impact ", 4],
    ["MODERATE", 3],
    ["neutral", 2],
    ["positive", 1],
  ];
  const moods = [
    ["critical", "Critical"],
    [" URGENT ", "Urgent"],
    ["concerned", "Concerned"],
    ["neutral", "Neutral"],
    ["satisfied", "Satisfied"],
  ];
  for (const [sentiment, expected] of impacts) {
    const rating = byKey(ticketSignalRatings(signalTicket({ ai_status: "completed", ai_reasoning: "evidence", sentiment })), "business-impact");
    assert.equal(rating.score, expected);
    assert.match(rating.detail, /^Classification: /);
  }
  for (const [mood, expectedLabel] of moods) {
    const sentiment = ticketSentimentPresentation(signalTicket({ ai_status: "completed", ai_reasoning: "evidence", mood }));
    assert.ok(sentiment);
    assert.match(sentiment.emoji, /^(😡|😣|😟|😐|😊)$/u);
    assert.equal(sentiment.label, expectedLabel);
  }
  assert.equal(byKey(ticketSignalRatings(signalTicket({ ai_status: "completed", ai_reasoning: "evidence", sentiment: "unknown", mood: "unknown" })), "business-impact").score, null);
  assert.equal(ticketSentimentPresentation(signalTicket({ ai_status: "completed", ai_reasoning: "evidence", mood: "unknown" })), null);
  assert.equal(ticketSentimentPresentation(signalTicket({ mood: "critical" })), null);
});

test("complexity rejects untrusted and out-of-contract values while rounding valid values", () => {
  const trusted = { ai_status: "completed", ai_reasoning: "evidence" };
  const cases = [
    [1, 1], [1.5, 2], [2.7, 3], [5, 5],
    [0, null], [-1, null], [6, null], [Number.NaN, null], [Number.POSITIVE_INFINITY, null], [undefined, null],
  ];
  for (const [complexity, expected] of cases) {
    assert.equal(byKey(ticketSignalRatings(signalTicket({ ...trusted, complexity })), "complexity").score, expected);
  }
  assert.equal(byKey(ticketSignalRatings(signalTicket({ complexity: 1 })), "complexity").score, null);
});

test("escalation risk maps exact bands and rejects malformed or unevidenced values", () => {
  const trusted = { ai_status: "completed", ai_reasoning: "evidence" };
  const cases = [
    [0, 1], [20, 1], [20.1, 2], [40, 2], [40.1, 3], [60, 3],
    [60.1, 4], [80, 4], [80.1, 5], [100, 5],
    [-1, null], [101, null], [Number.NaN, null], [Number.POSITIVE_INFINITY, null], [undefined, null],
  ];
  for (const [escalation_risk, expected] of cases) {
    assert.equal(byKey(ticketSignalRatings(signalTicket({ ...trusted, escalation_risk })), "escalation-risk").score, expected);
  }
  assert.equal(byKey(ticketSignalRatings(signalTicket({ escalation_risk: 0 })), "escalation-risk").score, null);
});

test("matching fresh analysis overrides persisted data and fails closed without reasoning", () => {
  const persisted = signalTicket({
    ai_status: "completed",
    ai_reasoning: "old evidence",
    sentiment: "Positive",
    mood: "satisfied",
    complexity: 1,
    escalation_risk: 0,
  });
  const fresh = ticketSignalRatings(persisted, freshAnalysis());
  assert.equal(byKey(fresh, "content-priority").score, 4);
  assert.match(byKey(fresh, "content-priority").detail, /Content supports P2; requester reported P3/);
  assert.equal(byKey(fresh, "business-impact").score, 3);
  assert.equal(ticketSentimentPresentation(persisted, freshAnalysis()).label, "Concerned");
  assert.equal(byKey(fresh, "complexity").score, 3);
  assert.equal(byKey(fresh, "escalation-risk").score, 3);

  const wrongTicket = ticketSignalRatings(persisted, { ...freshAnalysis(), ticket_id: "ticket-2" });
  assert.equal(byKey(wrongTicket, "business-impact").score, 1);

  const blankReasoning = ticketSignalRatings(persisted, freshAnalysis({ reasoning: "" }));
  for (const key of ["content-priority", "business-impact", "complexity", "escalation-risk"]) {
    assert.equal(byKey(blankReasoning, key).score, null);
    if (key === "content-priority") {
      assert.match(byKey(blankReasoning, key).detail, /^Analysis value unavailable; reported priority is P3$/);
    } else {
      assert.equal(byKey(blankReasoning, key).detail, "Analysis value unavailable");
    }
  }
  assert.equal(ticketSentimentPresentation(persisted, freshAnalysis({ reasoning: "" })), null);

  const malformedFresh = ticketSignalRatings(persisted, freshAnalysis({ sentiment: "unknown", complexity: 99 }));
  assert.equal(byKey(malformedFresh, "business-impact").score, null);
  assert.equal(byKey(malformedFresh, "complexity").score, null);
});
