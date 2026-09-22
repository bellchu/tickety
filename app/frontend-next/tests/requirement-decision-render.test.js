const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const query = require('@tanstack/react-query');
const ts = require('typescript');
const { loadPureTs } = require('./helpers/load-pure-ts');
const drafts = loadPureTs('requirement-editor-cache.ts');
const workspace = loadPureTs('requirement-workspace.ts');

function loadDecisionLog(overrides = {}) {
  const fileName = path.join(__dirname, '../components/requirements/DecisionLog.tsx');
  const output = ts.transpileModule(fs.readFileSync(fileName, 'utf8'), {
    fileName, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const loaded = { exports: {} };
  const dependencies = {
    react: React, 'react/jsx-runtime': require('react/jsx-runtime'),
    '@tanstack/react-query': query, './fields': { inputStyle: '' },
    '@/lib/requirement-workspace': workspace, '@/lib/requirement-editor-cache': drafts,
    '@/lib/requirement-errors': { requirementErrorMessage: String },
    '@/lib/api': { api: {}, APIError: Error },
    '@/lib/date-time': { formatLocalDateTime: value => value },
    '@/components/ui': {
      Button: ({ children, disabled, type }) => React.createElement('button', { disabled, type }, children),
      ConfirmDialog: () => null,
    },
  };
  Object.assign(dependencies, overrides);
  new Function('require', 'exports', 'module', output)(name => {
    if (!(name in dependencies)) throw new Error(`Unexpected dependency: ${name}`);
    return dependencies[name];
  }, loaded.exports, loaded);
  return loaded.exports.DecisionLog;
}
const DecisionLog = loadDecisionLog();
const decisions = Array.from({ length: 200 }, (_, index) => ({
  id: `d${index}`, requirement_id: 'r1', question: `Business question ${index}`,
  owner_role: 'Sponsor', status: 'open', blocking: true,
}));
function render({ open = true, scope = '', draft, pending = false } = {}) {
  const client = new query.QueryClient();
  if (draft) drafts.rememberRequirementDecisionDraft(client, 'owner', 'w1', draft);
  try {
    return renderToStaticMarkup(React.createElement(query.QueryClientProvider, { client },
      React.createElement(DecisionLog, {
        workspaceId: 'w1', userId: 'owner', requirements: [{ id: 'r1', reference: 'REQ-001', title: 'Receipt' }],
        decisions, open, scope, pending, onPendingChange() {}, seed: null, onToggle() {}, onScopeChange() {}, onSeedUsed() {}, async onSaved() {},
      })));
  } finally { client.clear(); }
}
test('large decision register renders only its first batch while totals cover all records', () => {
  const html = render();
  assert.equal((html.match(/<article/g) || []).length, 20);
  assert.ok(html.includes('Showing 20 of 200 matching records'));
  assert.ok(html.includes('Show more records'));
  assert.ok(!html.includes('Business question 199'));
});
test('restored answer beyond the first batch remains editable, including outside the selected scope', () => {
  const draft = { question: '', owner: '', requirementId: '', blocking: true, resolving: 'd199', resolution: 'Unsubmitted business rationale' };
  const html = render({ draft });
  assert.equal((html.match(/<article/g) || []).length, 21);
  assert.ok(html.includes('Business question 199'));
  assert.ok(html.includes('Unsubmitted business rationale</textarea>'));
  const scoped = render({ draft, scope: 'r2' });
  assert.equal((scoped.match(/<article/g) || []).length, 1);
  assert.ok(scoped.includes('Unsubmitted business rationale</textarea>'));
});
test('closed register does not render hidden decision cards or answer forms', () => {
  const html = render({ open: false });
  assert.equal((html.match(/<article/g) || []).length, 0);
  assert.ok(!html.includes('<textarea'));
  assert.ok(html.includes('200 open'));
});

test('workspace save blocks question submission and answer actions', () => {
  const html = render({ pending: true });
  assert.match(html, /<fieldset disabled=""/);
  assert.match(html, /<button disabled="" type="submit">Track question<\/button>/);
  assert.match(html, /<button disabled="">Record an answer<\/button>/);
});
test('workspace save also protects a restored answer until the shared operation finishes', () => {
  const draft = { question: '', owner: '', requirementId: '', blocking: true, resolving: 'd199', resolution: 'Unsubmitted business rationale' };
  const html = render({ pending: true, draft });
  assert.match(html, /<textarea disabled="" required=""/);
  assert.match(html, /<button disabled="" type="submit">Record decision<\/button>/);
  const ready = render({ pending: false, draft });
  assert.match(ready, /<button type="submit">Record decision<\/button>/);
});

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}
function findForm(node) {
  if (!node || typeof node !== 'object') return undefined;
  if (node.type === 'form') return node;
  return React.Children.toArray(node.props?.children).map(findForm).find(Boolean);
}
test('decision save reports busy through the request and subsequent refresh, then releases it', async () => {
  const request = deferred();
  const refresh = deferred();
  const changes = [];
  const client = new query.QueryClient();
  const Component = loadDecisionLog({
    react: { ...React, useState: initial => [typeof initial === 'function' ? initial() : initial, () => {}], useEffect() {}, useMemo: compute => compute() },
    '@tanstack/react-query': { useQueryClient: () => client },
    '@/lib/api': { api: { addRequirementDecision: () => request.promise }, APIError: Error },
  });
  try {
    const tree = Component({ workspaceId: 'w1', userId: 'owner', requirements: [], decisions: [], open: true,
      scope: '', seed: null, pending: false, onPendingChange: value => changes.push(value),
      onToggle() {}, onScopeChange() {}, onSeedUsed() {}, onSaved: () => refresh.promise });
    findForm(tree).props.onSubmit({ preventDefault() {} });
    assert.deepEqual(changes, [true], 'the workspace must know about the request immediately');
    request.resolve();
    await new Promise(setImmediate);
    assert.deepEqual(changes, [true], 'saved data is still refreshing');
    refresh.resolve();
    await new Promise(setImmediate);
    assert.deepEqual(changes, [true, false]);
  } finally { client.clear(); }
});
