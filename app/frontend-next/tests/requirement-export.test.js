const assert = require("node:assert/strict");
const test = require("node:test");

const { loadPureTs } = require('./helpers/load-pure-ts');
const library = loadPureTs('requirement-export.ts', { './requirement-workspace': loadPureTs('requirement-workspace.ts') });

test("BRD export retains evidence, human sign-off and story traceability", () => {
  const brief = library.requirementBrief({
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
  const brief = library.requirementBrief({
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
  const brief = library.requirementBrief({
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
  const brief = library.requirementBrief({
    workspace: { id: 'w', title: 'Future need', objective: 'Consider later', request_type: 'enhancement' }, sources: [],
    requirements: [{ reference: 'REQ-001', title: 'Later', status: 'validated', priority: 'wont', revision: 1, actor: 'Analyst', action: 'Review', benefit: 'Later', source_id: 's1', evidence_quote: 'Original business evidence.', acceptance_criteria: [], quality_issues: [], story: { reference: 'US-001', title: 'Old story', statement: 'Old delivery wording' } }],
  });
  assert.ok(brief.includes('Deferred — not this time'));
  assert.ok(brief.includes('Original business evidence.'));
  assert.ok(!brief.includes('Old delivery wording'));
  assert.ok(brief.includes('0 user stories prepared'));
});

test('copied stories include signed criteria, provenance and only relevant open questions', () => {
  const row = { id: 'r1', status: 'validated', priority: 'must', source_id: 's1', evidence_quote: 'Confirm the submission within thirty seconds.', validated_by: 'reviewer', reviewer_role: 'Product Owner', validated_at: '2026-09-21T00:00:00Z', validation_note: 'Confirmed with operations.', story: { reference: 'US-001', title: 'Receipt', statement: 'As an analyst, I want a receipt, so that I can track intake.', acceptance_criteria: ['Given valid input, a receipt appears within 30 seconds.'], requirement_reference: 'REQ-001', validated_revision: 2 } };
  const detail = { workspace: { id: 'w', title: 'Supplier intake', objective: 'Reduce manual follow-up.' }, sources: [{ id: 's1', title: 'Operations SOP', content_sha256: 'digest' }], decisions: [
    { requirement_id: null, status: 'open', blocking: false, question: 'Which languages might be added later?', owner_role: 'Sponsor' },
    { requirement_id: 'r1', status: 'open', blocking: false, question: 'Could receipt text be configurable?', owner_role: 'Analyst' },
    { requirement_id: 'r2', status: 'open', question: 'Unrelated requirement question' },
    { requirement_id: 'r1', status: 'resolved', question: 'Already answered question' },
  ] };
  const output = library.requirementStoryText(detail, row);
  for (const required of ['US-001', 'REQ-001', 'Business priority: Must have', 'Delivery scope: Included in the current initiative', 'signed-off revision 2', '30 seconds', 'Operations SOP', 'digest', 'Confirm the submission', 'Product Owner', 'Confirmed with operations.', 'Which languages', 'Could receipt text', 'Reduce manual follow-up.']) assert.ok(output.includes(required), required);
  assert.ok(!output.includes('Unrelated requirement question'));
  assert.ok(output.includes('Already answered question'));
  assert.throws(() => library.requirementStoryText(detail, { ...row, priority: 'wont' }), /in-scope/);
  assert.throws(() => library.requirementStoryText(detail, { ...row, status: 'draft' }), /signed-off/);
});

test('exports keep multiline evidence literal and user text inside its own structure', () => {
  const evidence = 'Original excerpt\n```\n## Quoted heading\n<script>example</script>\n```';
  const row = { id: 'r1', reference: 'REQ-001', title: 'Title\n## Not a new section', actor: 'Analyst', action: 'Confirm receipt', benefit: 'Avoid delays', source_id: 's1', evidence_quote: evidence,
    acceptance_criteria: ['Confirm receipt\n- include timestamp'], quality_issues: [], priority: 'must', status: 'validated', revision: 2,
    validated_by: 'reviewer', reviewer_role: 'Product Owner', validated_at: '2026-09-22', validation_note: '<b>Reviewed</b>',
    story: { reference: 'US-001', title: '[Receipt](https://example.test)', statement: 'As an analyst, I want receipt.', acceptance_criteria: ['Confirm receipt\n- include timestamp'], requirement_reference: 'REQ-001', validated_revision: 2 } };
  const detail = { workspace: { id: 'w1', title: 'Intake\n# Extra heading', objective: 'Context\n---\n## Quoted title\n~~~\nSample text', request_type: 'enhancement' }, sources: [{ id: 's1', title: 'SOP', kind: 'sop', content_sha256: 'digest' }], requirements: [row], decisions: [] };
  for (const output of [library.requirementBrief(detail), library.requirementStoryText(detail, row)]) {
    assert.ok(output.includes('````text\n' + evidence + '\n````'));
    assert.ok(output.includes('- Confirm receipt\n  \\- include timestamp'));
    assert.ok(output.includes('\\<b\\>Reviewed\\</b\\>'));
    assert.ok(!output.includes('\n# Extra heading'));
    assert.ok(!output.includes('\n~~~'));
    assert.ok(!output.includes('\n---\n'));
  }
});


test('story handoff preserves relevant business decisions and their attribution', () => {
  const row = { id: 'r1', status: 'validated', priority: 'must', source_id: 's1', evidence_quote: 'Confirm receipt.', story: { reference: 'US-001', title: 'Receipt', statement: 'Confirm receipt.', acceptance_criteria: [], requirement_reference: 'REQ-001', validated_revision: 2 } };
  const detail = { workspace: { id: 'w', title: 'Intake', objective: 'Reduce delays' }, sources: [], decisions: [
    { requirement_id: null, status: 'resolved', question: 'Who owns failures?', owner_role: 'Operations', resolution: 'Queue and retry within five minutes.', resolved_by: 'reviewer-1', resolved_at: '2026-09-22T10:00:00Z' },
    { requirement_id: 'r1', status: 'resolved', question: 'Which channels?', owner_role: 'Sponsor', resolution: 'Email only.\n## Quoted context', resolved_by: 'reviewer-2', resolved_at: '2026-09-22T11:00:00Z' },
    { requirement_id: 'r2', status: 'resolved', question: 'Unrelated scope', resolution: 'Unrelated decision' },
  ] };
  const output = library.requirementStoryText(detail, row);
  for (const value of ['Who owns failures?', 'Queue and retry within five minutes.', 'Whole initiative', 'Which channels?', 'This requirement', 'Operations', 'Sponsor', 'reviewer-1', 'reviewer-2', '2026-09-22T10:00:00Z']) assert.ok(output.includes(value), value);
  assert.ok(!output.includes('Unrelated decision'));
  assert.ok(!output.includes('\n## Quoted context'));
  assert.ok(output.includes('No open questions are recorded'));
  assert.ok(library.requirementStoryText({ ...detail, decisions: [] }, row).includes('No business decisions are recorded'));
});


test('brief readiness distinguishes drafts, agreed work, prepared stories and deferred scope', () => {
  const base = { reference: 'REQ-001', title: 'Need', revision: 1, actor: 'Analyst', action: 'Confirm receipt', benefit: 'Avoid delays', source_id: 's', evidence_quote: 'Confirm receipt within thirty seconds.', acceptance_criteria: [], quality_issues: [], story: null };
  const requirements = [
    { ...base, status: 'draft', priority: 'must' },
    { ...base, status: 'validated', priority: 'should' },
    { ...base, status: 'validated', priority: 'could', story: { reference: 'US-003', title: 'Receipt', statement: 'Confirm receipt', requirement_reference: 'REQ-003', validated_revision: 1 } },
    { ...base, status: 'draft', priority: 'wont' },
  ];
  const output = library.requirementBrief({ workspace: { id: 'w', title: 'Intake', objective: 'Reduce delays', request_type: 'enhancement' }, sources: [], requirements, decisions: [] });
  for (const line of ['Included in this initiative: 3 requirements', 'Drafts awaiting agreement: 1', 'Signed off, awaiting story preparation: 1', 'User stories prepared for delivery-team review: 1', 'Deferred — not this time: 1', 'Inclusion is not sign-off']) assert.ok(output.includes(line), line);
  assert.ok(output.indexOf('## Scope and readiness') < output.indexOf('## Evidence register'));
});


test('evidence register maps sources to requirements without losing deferred or supporting context', () => {
  const row = { title: 'Receipt', revision: 1, status: 'draft', actor: 'Analyst', action: 'Confirm receipt', benefit: 'Avoid delays', evidence_quote: 'Confirm receipt within thirty seconds.', acceptance_criteria: [], quality_issues: [], story: null };
  const brief = library.requirementBrief({ workspace: { id: 'w', title: 'Intake', objective: 'Reduce delays', request_type: 'enhancement' },
    sources: [{ id: 's1', title: 'Operations SOP', kind: 'sop', content_sha256: 'digest-one' }, { id: 's2', title: 'Background interview', kind: 'transcript', content_sha256: 'digest-two' }],
    requirements: [{ ...row, reference: 'REQ-001', source_id: 's1', priority: 'must' }, { ...row, reference: 'REQ-002', source_id: 's1', priority: 'wont' }], decisions: [] });
  const register = brief.split('## Evidence register')[1].split('## Documented requirements')[0];
  assert.ok(register.includes('Supports: REQ-001, REQ-002 (deferred)'));
  assert.ok(register.includes('Background interview'));
  assert.ok(register.includes('Supporting context — no linked requirements recorded.'));
  assert.ok(register.includes('digest-one'));
  assert.ok(register.includes('digest-two'));
});

test('brief distinguishes deferred blockers without losing global or unknown-scope questions', () => {
  const row = { id: 'deferred', reference: 'REQ-009', title: 'Later', priority: 'wont', status: 'draft', revision: 1,
    actor: '', action: '', benefit: '', source_id: 's1', evidence_quote: 'Supporting material.', acceptance_criteria: [], quality_issues: [], story: null };
  const blocker = { status: 'open', blocking: true, owner_role: 'Sponsor', question: 'Confirm responsibility?' };
  const output = library.requirementBrief({
    workspace: { id: 'w1', title: 'Scope review', objective: 'Agree delivery scope', request_type: 'enhancement' },
    sources: [], requirements: [row], decisions: [
      { ...blocker, requirement_id: 'deferred' },
      { ...blocker, requirement_id: null },
      { ...blocker, requirement_id: 'missing' },
      { ...blocker, requirement_id: 'deferred', status: 'resolved', resolution: 'Confirmed' },
      { ...blocker, requirement_id: 'deferred', blocking: false },
    ],
  });
  assert.ok(output.includes('Open blocking business questions: 3'));
  assert.ok(output.includes('Affecting current scope or requiring scope confirmation: 2'));
  assert.ok(output.includes('Linked only to deferred requirements: 1'));
  assert.ok(output.includes('Scope: REQ-009'));
  assert.ok(output.includes('Scope: missing'));
  assert.ok(output.includes('3 blocking business questions remain'));
});

test('brief filenames identify initiatives and remain safe across filesystem conventions', () => {
  const filename = library.requirementBriefFilename;
  assert.equal(filename({ title: 'Supplier onboarding', id: 'w1' }), 'requirements-Supplier-onboarding-w1.md');
  assert.notEqual(filename({ title: 'Same name', id: 'w1' }), filename({ title: 'Same name', id: 'w2' }));
  assert.equal(filename({ title: '../CON: "scope"\\file?', id: 'w1' }), 'requirements-CON-scope-file-w1.md');
  assert.equal(filename({ title: '采购需求', id: 'w1' }), 'requirements-采购需求-w1.md');
  assert.equal(filename({ title: '...', id: 'w1' }), 'requirements-untitled-w1.md');
  const long = filename({ title: '采购'.repeat(200), id: '12345678-1234-1234-1234-123456789012' });
  assert.ok(Buffer.byteLength(long, 'utf8') < 255);
  assert.ok(!/[\\/:*?"<>|]/.test(long));
});
