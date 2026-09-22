const assert = require('node:assert/strict');
const test = require('node:test');
const { loadPureTs } = require('./helpers/load-pure-ts');
const { reviewQuestionDraft } = loadPureTs('requirement-review-question.ts');

test('review questions retain their full context and reviewed revisions as a human-confirmed draft', () => {
  const result = reviewQuestionDraft('Who owns retry handling?', 'The normal path is described.\nThe retry owner is unclear.', [{ reference: 'REQ-002', revision: 7 }, { reference: 'REQ-001', revision: 3 }]);
  assert.equal(result, 'AI review · REQ-002 r7, REQ-001 r3\nQuestion: Who owns retry handling?\n\nContext to confirm: The normal path is described.\nThe retry owner is unclear.');
});

test('maximum AI output keeps the whole question and fits the decision limit using Unicode characters', () => {
  const question = '问'.repeat(2000);
  const finding = '😀'.repeat(2000);
  const snapshots = Array.from({ length: 8 }, (_, index) => ({ reference: `REQ-00${index + 1}`, revision: 12345 }));
  const result = reviewQuestionDraft(question, finding, snapshots);
  assert.equal(Array.from(result).length, 4000);
  assert.ok(result.includes(`Question: ${question}\n`));
  for (const snapshot of snapshots) assert.ok(result.includes(`${snapshot.reference} r12345`));
  assert.ok(result.endsWith('… [context shortened]'));
  assert.ok(!result.includes('\uFFFD'));
});
