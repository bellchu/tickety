const assert = require('node:assert/strict');
const test = require('node:test');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { loadPureTs, loadComponentTs } = require('./helpers/load-pure-ts');
const { SignOffDecisions } = loadComponentTs('requirements/SignOffDecisions.tsx', {
  react: React, 'react/jsx-runtime': require('react/jsx-runtime'),
  '@/lib/date-time': { formatLocalDateTime: value => `Local time: ${value}` },
  '@/lib/requirement-workspace': loadPureTs('requirement-workspace.ts'),
});
const render = decisions => renderToStaticMarkup(React.createElement(SignOffDecisions, { requirementId: 'r1', decisions }));

test('sign-off context includes global and scoped decisions with distinct unresolved gates', () => {
  const base = { owner_role: 'Sponsor', blocking: true, status: 'open', resolution: null };
  const html = render([
    { ...base, id: 'global', requirement_id: null, question: 'Global answer', status: 'resolved', resolution: 'Use the Operations queue.' },
    { ...base, id: 'blocking', requirement_id: 'r1', question: 'Who owns recovery?' },
    { ...base, id: 'optional', requirement_id: 'r1', blocking: false, question: 'Future channel?' },
    { ...base, id: 'other', requirement_id: 'r2', question: 'Unrelated confidential scope' },
  ]);
  assert.ok(html.includes('1 recorded · 1 blocking · 1 exploratory'));
  assert.ok(html.includes('Use the Operations queue.'));
  assert.ok(html.includes('Whole initiative'));
  assert.ok(html.includes('This requirement'));
  assert.ok(html.includes('Blocks sign-off'));
  assert.ok(html.includes('Future channel?'));
  assert.ok(!html.includes('Unrelated confidential scope'));
  assert.ok(!html.includes('<button'));
});
test('an empty decision register does not imply that all assumptions were resolved', () => {
  assert.ok(render([]).includes('Confirm any unresolved assumptions with the stakeholder.'));
});

test('sign-off puts late blockers ahead of historical answers without changing saved order', () => {
  const records = [
    { id: 'old', requirement_id: 'r1', question: 'Earlier answer', status: 'resolved', blocking: true, resolution: 'Agreed approach' },
    { id: 'explore', requirement_id: null, question: 'Future exploration', status: 'open', blocking: false },
    { id: 'block', requirement_id: 'r1', question: 'Late blocking question', status: 'open', blocking: true },
    { id: 'global', requirement_id: null, question: 'Global blocking question', status: 'open', blocking: true },
  ];
  const html = render(records);
  assert.ok(html.indexOf('Late blocking question') < html.indexOf('Global blocking question'));
  assert.ok(html.indexOf('Global blocking question') < html.indexOf('Earlier answer'));
  assert.ok(html.indexOf('Earlier answer') < html.indexOf('Future exploration'));
  assert.deepEqual(records.map(item => item.id), ['old', 'explore', 'block', 'global']);
});


test('recorded decisions expose provenance during sign-off without inventing missing details', () => {
  const base = { id: 'd1', requirement_id: 'r1', question: 'Who owns recovery?', status: 'resolved', blocking: true, resolution: 'Operations owns recovery.' };
  const html = render([{ ...base, resolved_by: 'reviewer-1', resolved_at: '2026-09-22T10:00:00Z' }]);
  assert.ok(html.includes('Recorded by reviewer-1'));
  assert.ok(html.includes('Local time: 2026-09-22T10:00:00Z'));
  const missing = render([base]);
  assert.ok(missing.includes('Former member'));
  assert.ok(missing.includes('Time not recorded'));
  assert.ok(!render([{ ...base, status: 'open', resolution: null }]).includes('Recorded by'));
});
