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

function loadDecisionLog() {
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
function render({ open = true, scope = '', draft } = {}) {
  const client = new query.QueryClient();
  if (draft) drafts.rememberRequirementDecisionDraft(client, 'owner', 'w1', draft);
  try {
    return renderToStaticMarkup(React.createElement(query.QueryClientProvider, { client },
      React.createElement(DecisionLog, {
        workspaceId: 'w1', userId: 'owner', requirements: [{ id: 'r1', reference: 'REQ-001', title: 'Receipt' }],
        decisions, open, scope, seed: null, onToggle() {}, onScopeChange() {}, onSeedUsed() {}, async onSaved() {},
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
