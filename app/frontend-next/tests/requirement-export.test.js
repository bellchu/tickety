const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

const output = ts.transpileModule(fs.readFileSync(path.join(__dirname, "../lib/requirement-export.ts"), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const loaded = { exports: {} };
new Function("exports", "module", output)(loaded.exports, loaded);

test("BRD export retains evidence, human sign-off and story traceability", () => {
  const brief = loaded.exports.requirementBrief({
    workspace: { id: "initiative-1", title: "Invoice intake", objective: "Reduce delays", request_type: "enhancement" },
    sources: [{ id: "source-1", title: "Finance SOP", kind: "sop", content_sha256: "abc123" }],
    requirements: [{
      reference: "REQ-001", title: "Acknowledge invoices", status: "validated", priority: "must", revision: 3,
      actor: "analyst", action: "receive confirmation", benefit: "I can track intake", source_id: "source-1",
      evidence_quote: "Confirm receipt within 30 seconds.", acceptance_criteria: ["Receipt appears within 30 seconds."],
      quality_issues: [], validated_by: "reviewer-1", reviewer_role: "Product Owner", validated_at: "2026-09-21T00:00:00Z",
      validation_note: "Confirmed with finance.", story: { reference: "US-001", title: "Confirmation", statement: "As an analyst, I want confirmation.", requirement_reference: "REQ-001", validated_revision: 2 },
    }],
  });
  for (const evidence of ["Request type: Enhancement", "REQ-001", "US-001", "source-1", "abc123", "Confirm receipt within 30 seconds.", "reviewer-1", "Product Owner", "Confirmed with finance.", "validated revision 2"]) {
    assert.ok(brief.includes(evidence), evidence);
  }
});

test("draft exports retain open questions without fabricating sign-off", () => {
  const brief = loaded.exports.requirementBrief({
    workspace: { id: "initiative-2", title: "Draft", objective: "Discover the outcome", request_type: "approved_project" },
    sources: [],
    requirements: [{ reference: "REQ-001", title: "Open question", status: "draft", priority: "should", revision: 1,
      actor: "", action: "", benefit: "", source_id: "source-2", evidence_quote: "Investigate the process.", acceptance_criteria: [],
      quality_issues: ["Add the business outcome."], validated_at: null, story: null }],
  });
  assert.ok(brief.includes("Open clarification items:"));
  assert.ok(brief.includes("Add the business outcome."));
  assert.ok(!brief.includes("Signed off by"));
});

test("BRD carries business decisions and reports unresolved blockers honestly", () => {
  const brief = loaded.exports.requirementBrief({
    workspace: { id: "w", title: "Supplier intake", objective: "Reduce delays", request_type: "enhancement" },
    sources: [], requirements: [], decisions: [
      { question: "Who owns delivery failures?", owner_role: "Operations lead", requirement_id: null, status: "open", blocking: true, resolution: null },
      { question: "Which deadline was agreed?", owner_role: "Sponsor", requirement_id: null, status: "resolved", blocking: true, resolution: "Within five minutes", resolved_by: "reviewer-1", resolved_at: "2026-09-21T00:00:00Z" },
    ],
  });
  for (const value of ["Who owns delivery failures?", "Operations lead", "Whole initiative", "Within five minutes", "reviewer-1", "0 user stories prepared", "1 blocking business questions remain"]) assert.ok(brief.includes(value), value);
  assert.ok(!brief.includes("User stories are ready"));
});

test('deferred needs retain their evidence without exporting an old story as delivery work', () => {
  const brief = loaded.exports.requirementBrief({
    workspace: { id: 'w', title: 'Future need', objective: 'Consider later', request_type: 'enhancement' }, sources: [],
    requirements: [{ reference: 'REQ-001', title: 'Later', status: 'validated', priority: 'wont', revision: 1, actor: 'Analyst', action: 'Review', benefit: 'Later', source_id: 's1', evidence_quote: 'Original business evidence.', acceptance_criteria: [], quality_issues: [], story: { reference: 'US-001', title: 'Old story', statement: 'Old delivery wording' } }],
  });
  assert.ok(brief.includes('Deferred — not this time'));
  assert.ok(brief.includes('Original business evidence.'));
  assert.ok(!brief.includes('Old delivery wording'));
  assert.ok(brief.includes('0 user stories prepared'));
});
