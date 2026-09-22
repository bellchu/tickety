const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const ts = require('typescript');
const output = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../lib/requirement-workspace.ts'), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const loaded = { exports: {} };
new Function('exports', 'module', output)(loaded.exports, loaded);
const { workspaceFocus, filterRequirements } = loaded.exports;
const item = { id: 'r1', reference: 'REQ-001', title: 'Receipt', actor: 'Analyst', action: 'Track intake', benefit: 'Avoid delays', source_id: 's1', status: 'draft', quality_issues: [], story: null };
const detail = (items = [], sources = [{ id: 's1', title: 'SOP' }]) => ({ requirements: items, sources });
test('focus follows evidence and unresolved business questions before sign-off', () => {
  assert.equal(workspaceFocus(detail([], [])).action, 'source');
  assert.equal(workspaceFocus(detail()).action, 'gather');
  assert.equal(workspaceFocus(detail([item])).action, 'review');
  assert.equal(workspaceFocus(detail([item, { ...item, id: 'r2', quality_issues: ['Confirm outcome'] }])).action, 'questions');
});
test('agreement permits story preparation and revisions return to review', () => {
  const agreed = { ...item, status: 'validated' };
  assert.equal(workspaceFocus(detail([agreed])).action, 'story');
  assert.equal(workspaceFocus(detail([{ ...agreed, story: {} }])).action, 'export');
  assert.equal(workspaceFocus(detail([item])).action, 'review');
});
test('new evidence reopens exploration even when existing work has stories', () => {
  assert.equal(workspaceFocus(detail([{ ...item, status: 'validated', story: {} }], [{ id: 's1', title: 'SOP' }, { id: 's2', title: 'New policy' }])).sourceId, 's2');
});
test('search combines with readiness filters without treating agreement as a story', () => {
  const items = [item, { ...item, id: 'r2', quality_issues: ['Clarify'] }, { ...item, id: 'r3', status: 'validated' }, { ...item, id: 'r4', status: 'validated', story: {} }];
  assert.deepEqual(filterRequirements(items, ' ANALYST ', 'review').map(x => x.id), ['r1']);
  assert.deepEqual(filterRequirements(items, '', 'questions').map(x => x.id), ['r2']);
  assert.deepEqual(filterRequirements(items, '', 'delivery').map(x => x.id), ['r4']);
  assert.equal(filterRequirements(items, 'missing', 'all').length, 0);
});
test('business blockers take precedence and affect only their scope in filtered views', () => {
  const decisions = [{ requirement_id: 'r1', blocking: true, status: 'open', owner_role: 'Sponsor', question: 'Who owns the exception path?' }];
  assert.equal(workspaceFocus({ ...detail([item]), decisions }).action, 'decisions');
  assert.equal(filterRequirements([item], '', 'review', decisions).length, 0);
  assert.equal(filterRequirements([item], '', 'questions', decisions).length, 1);
  assert.equal(filterRequirements([{ ...item, id: 'r2' }], '', 'review', decisions).length, 1);
  assert.equal(workspaceFocus({ ...detail([item]), decisions: [{ ...decisions[0], status: 'resolved' }] }).action, 'review');
});
test('deferred requirements remain discoverable without demanding review or delivery', () => {
  const deferred = { ...item, priority: 'wont', quality_issues: ['Clarify the future outcome'] };
  assert.equal(workspaceFocus(detail([deferred])).action, 'deferred');
  assert.equal(filterRequirements([deferred], '', 'all').length, 1);
  assert.equal(filterRequirements([deferred], '', 'deferred').length, 1);
  for (const filter of ['questions', 'review', 'delivery']) assert.equal(filterRequirements([{ ...deferred, story: {} }], '', filter).length, 0);
  const current = { ...item, id: 'r2' };
  const decisions = [{ requirement_id: 'r1', blocking: true, status: 'open', owner_role: 'Sponsor', question: 'Future question' }];
  assert.equal(workspaceFocus({ ...detail([deferred, current]), decisions }).item.id, 'r2');
});
