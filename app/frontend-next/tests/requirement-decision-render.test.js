const { descendants } = require('./helpers/react-tree');
const assert = require('node:assert/strict');
const test = require('node:test');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const query = require('@tanstack/react-query');
const { loadPureTs, loadComponentTs } = require('./helpers/load-pure-ts');
const drafts = loadPureTs('requirement-editor-cache.ts');
const workspace = loadPureTs('requirement-workspace.ts');

function loadDecisionLog(overrides = {}) {
  const dependencies = {
    './BoundedText': loadComponentTs('requirements/BoundedText.tsx', {
      'react/jsx-runtime': require('react/jsx-runtime'), '@/lib/requirement-text': loadPureTs('requirement-text.ts'),
    }),
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
  const { DecisionLog } = loadComponentTs('requirements/DecisionLog.tsx', dependencies);
  return DecisionLog;
}
const DecisionLog = loadDecisionLog();
const decisions = Array.from({ length: 200 }, (_, index) => ({
  id: `d${index}`, requirement_id: 'r1', question: `Business question ${index}`,
  owner_role: 'Sponsor', status: 'open', blocking: true,
}));
function render({ open = true, scope = '', draft, pending = false, records = decisions, decisionRequest, requirements = [{ id: 'r1', reference: 'REQ-001', title: 'Receipt' }] } = {}) {
  const client = new query.QueryClient();
  if (draft) drafts.rememberRequirementDecisionDraft(client, 'owner', 'w1', draft);
  try {
    return renderToStaticMarkup(React.createElement(query.QueryClientProvider, { client },
      React.createElement(DecisionLog, {
        workspaceId: 'w1', userId: 'owner', requirements,
        decisions: records, open, scope, pending, decisionRequest, onFindRequirements() {}, onPendingChange() {}, seed: null, onToggle() {}, onScopeChange() {}, onSeedUsed() {}, async onSaved() {},
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

test('suggested question beyond the first batch is placed first without losing another answer draft', () => {
  const draft = { question: '', owner: '', requirementId: '', blocking: true, resolving: 'd198', resolution: 'Keep this unfinished answer' };
  const html = render({ decisionRequest: { id: 'd199' }, draft });
  assert.ok(html.includes('Suggested business question'));
  assert.ok(html.indexOf('Business question 199') < html.indexOf('Business question 0'));
  assert.ok(html.includes('Keep this unfinished answer</textarea>'));
  assert.equal((html.match(/<article/g) || []).length, 21);
  assert.equal(decisions[0].id, 'd0');
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

test('decision navigation distinguishes a known requirement, whole initiative and unavailable scope', () => {
  const html = render({ records: [
    { ...decisions[0], id: 'known', requirement_id: 'r1' },
    { ...decisions[0], id: 'global', requirement_id: null },
    { ...decisions[0], id: 'missing', requirement_id: 'removed' },
  ] });
  assert.equal((html.match(/href="#requirement-list"/g) || []).length, 2);
  assert.ok(html.includes('Find REQ-001'));
  assert.ok(html.includes('View initiative requirements'));
  assert.ok(html.includes('Requirement unavailable'));
});

test('recording an answer retains an actionable follow-up after the open question disappears', async () => {
  const client = new query.QueryClient();
  const draft = { question: '', owner: '', requirementId: '', blocking: true, resolving: 'd0', resolution: 'Agreed receipt within thirty seconds' };
  drafts.rememberRequirementDecisionDraft(client, 'owner', 'w1', draft);
  const state = [];
  let cursor = 0;
  let pending = false;
  let saved = false;
  const targets = [];
  const Component = loadDecisionLog({
    react: { ...React, useEffect() {}, useMemo: compute => compute(), useState(initial) {
      const index = cursor++;
      if (!(index in state)) state[index] = typeof initial === 'function' ? initial() : initial;
      return [state[index], value => { state[index] = typeof value === 'function' ? value(state[index]) : value; }];
    } },
    '@tanstack/react-query': { useQueryClient: () => client },
    '@/lib/api': { api: { async resolveRequirementDecision(id, decisionId, answer) {
      assert.equal(id, 'w1'); assert.equal(decisionId, 'd0'); assert.equal(answer, draft.resolution);
    } }, APIError: Error },
  });
  function renderTree() {
    cursor = 0;
    return Component({ workspaceId: 'w1', userId: 'owner', requirements: [{ id: 'r1', reference: 'REQ-001' }],
      decisions: saved ? [{ ...decisions[0], status: 'resolved', resolution: draft.resolution }] : [decisions[0]],
      open: true, scope: '', seed: null, pending, onPendingChange: value => { pending = value; },
      onToggle() {}, onScopeChange() {}, onSeedUsed() {}, onFindRequirements: id => targets.push(id),
      async onSaved() { saved = true; } });
  }
  try {
    descendants(renderTree(), 'form')[1].props.onSubmit({ preventDefault() {} });
    assert.equal(pending, true);
    await new Promise(setImmediate);
    assert.equal(pending, false);
    const tree = renderTree();
    const html = renderToStaticMarkup(tree);
    assert.ok(html.includes('Decision recorded. Check the affected requirements'));
    assert.ok(!html.includes('Business question 0'));
    const link = descendants(tree, 'a').find(item => item.props.href === '#requirement-list');
    link.props.onClick();
    assert.deepEqual(targets, ['r1']);
  } finally { client.clear(); }
});

test('opening a suggestion clears old register filters without changing an answer', () => {
  const client = new query.QueryClient();
  const draft = { question: '', owner: '', requirementId: '', blocking: true, resolving: 'd198', resolution: 'Preserved answer rationale' };
  drafts.rememberRequirementDecisionDraft(client, 'owner', 'w1', draft);
  const state = [], effects = [];
  let cursor = 0;
  const Component = loadDecisionLog({
    react: { ...React, useMemo: compute => compute(), useEffect: effect => effects.push(effect), useState(initial) {
      const index = cursor++;
      if (!(index in state)) state[index] = typeof initial === 'function' ? initial() : initial;
      return [state[index], value => { state[index] = typeof value === 'function' ? value(state[index]) : value; }];
    } },
    '@tanstack/react-query': { useQueryClient: () => client },
  });
  function tree(decisionRequest) {
    cursor = 0; effects.length = 0;
    return Component({ workspaceId: 'w1', userId: 'owner', requirements: [], decisions,
      open: true, scope: '', seed: null, pending: false, decisionRequest, onFindRequirements() {} });
  }
  try {
    const first = tree(null);
    descendants(first, 'input').find(node => node.props.type === 'search').props.onChange({ target: { value: 'No matching question' } });
    descendants(first, 'select').find(node => node.props.value === 'open').props.onChange({ target: { value: 'recorded' } });
    assert.ok(!renderToStaticMarkup(tree(null)).includes('Business question 199'));
    const request = { id: 'd199' };
    tree(request);
    effects.forEach(effect => effect());
    const html = renderToStaticMarkup(tree(request));
    assert.ok(html.includes('Business question 199'));
    assert.ok(!html.includes('No matching question'));
    assert.ok(html.includes('Preserved answer rationale</textarea>'));
    const historyRequest = { id: '', includeRecorded: true };
    tree(historyRequest);
    effects.forEach(effect => effect());
    const historyTree = tree(historyRequest);
    assert.ok(descendants(historyTree, 'select').some(node => node.props.value === 'all'));
    assert.ok(renderToStaticMarkup(historyTree).includes('Preserved answer rationale</textarea>'));
  } finally { client.clear(); }
});


test('collapsed decision summary separates deferred blockers from current or unknown scope', () => {
  const records = [
    { ...decisions[0], id: 'deferred', requirement_id: 'later' },
    { ...decisions[0], id: 'global', requirement_id: null },
    { ...decisions[0], id: 'unknown', requirement_id: 'missing' },
    { ...decisions[0], id: 'resolved', status: 'resolved' },
    { ...decisions[0], id: 'exploratory', blocking: false },
  ];
  const html = render({ open: false, records, requirements: [{ id: 'later', reference: 'REQ-002', title: 'Later', priority: 'wont' }] });
  assert.ok(html.includes('2 affect current scope or need scope confirmation'));
  assert.ok(html.includes('1 relate only to deferred requirements'));
  assert.ok(!html.includes('<article'));
  assert.ok(!render({ records: [] }).includes('affect current scope'));
});
