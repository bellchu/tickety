const assert = require('node:assert/strict');
const test = require('node:test');
const { loadPureTs } = require('./helpers/load-pure-ts');
const { requirementChanges, requirementChangeSummary } = loadPureTs('requirement-history.ts');
const original = { title: 'Receipt', status: 'validated', priority: 'must', acceptance_criteria: ['Within 30 seconds'], story: { statement: 'Agreed story' } };

test('history summary explains business edits and loss of agreement and story', () => {
  const updated = { ...original, acceptance_criteria: ['Within five minutes'], status: 'draft', story: null };
  const summary = requirementChangeSummary(original, updated);
  assert.match(summary, /Changed: Acceptance criteria/);
  assert.match(summary, /new sign-off is required/);
  assert.match(summary, /Previous user story withdrawn/);
  assert.deepEqual(requirementChanges(original, updated).map(([key]) => key), ['acceptance_criteria', 'status', 'story']);
});
test('history distinguishes scope changes, sign-off and story preparation', () => {
  assert.match(requirementChangeSummary(original, { ...original, priority: 'wont' }), /Removed from current delivery scope/);
  assert.match(requirementChangeSummary({ ...original, priority: 'wont' }, original), /Returned to current delivery scope/);
  assert.match(requirementChangeSummary({ ...original, status: 'draft' }, original), /Business agreement recorded/);
  assert.match(requirementChangeSummary({ ...original, story: null }, original), /User story prepared/);
  assert.match(requirementChangeSummary(null, original), /Initial evidence/);
  assert.equal(requirementChangeSummary(original, { ...original, revision: 9 }), 'No tracked field changes.');
});
