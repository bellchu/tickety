const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { loadPureTs } = require('./helpers/load-pure-ts');
const fileName = path.join(__dirname, '../components/requirements/SignOffDecisions.tsx');
const output = ts.transpileModule(fs.readFileSync(fileName, 'utf8'), {
  fileName, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const loaded = { exports: {} };
new Function('require', 'exports', output)(name => {
  if (name === 'react/jsx-runtime') return require(name);
  if (name === '@/lib/requirement-workspace') return loadPureTs('requirement-workspace.ts');
  throw new Error(`Unexpected dependency: ${name}`);
}, loaded.exports);
const render = decisions => renderToStaticMarkup(React.createElement(loaded.exports.SignOffDecisions, { requirementId: 'r1', decisions }));

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
