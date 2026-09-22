const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const ts = require('typescript');
const { loadPureTs } = require('./helpers/load-pure-ts');
const fileName = path.join(__dirname, '../components/requirements/AIRequirementReview.tsx');
const output = ts.transpileModule(fs.readFileSync(fileName, 'utf8'), {
  fileName, compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
}).outputText;
const loaded = { exports: {} };
const dependencies = {
  'react/jsx-runtime': require('react/jsx-runtime'), './fields': { panelStyle: '' },
  '@/lib/requirement-workspace': loadPureTs('requirement-workspace.ts'),
  '@/components/ui': { Button: ({ children, disabled }) => React.createElement('button', { disabled }, children) },
};
new Function('require', 'exports', 'module', output)(name => {
  if (!(name in dependencies)) throw new Error(`Unexpected dependency: ${name}`);
  return dependencies[name];
}, loaded.exports, loaded);
const item = { id: 'r1', reference: 'REQ-001', revision: 2, status: 'validated', priority: 'must' };
function render(current, mode = 'story', busy = false) {
  return renderToStaticMarkup(React.createElement(loaded.exports.AIRequirementReview, {
    assistance: { item, result: { mode, model: 'Configured provider', base_revision: 2, input_truncated: true,
      suggestions: { actor: 'Analyst', action: 'confirm receipt', benefit: 'track requests', assumptions: ['Confirm target'], questions: ['Who owns failures?'] } } },
    current, busy, onDismiss() {}, onQuestion() {}, onReanalyze() {}, onRefine() {},
  }));
}
test('current AI suggestions retain the human review warning and enabled draft action', () => {
  const html = render(item);
  assert.ok(html.includes('<button>Review as a new revision</button>'));
  assert.ok(html.includes('requires a new sign-off'));
  assert.ok(html.includes('covers only part of the requirement'));
  assert.ok(!html.includes('Analyze current version'));
});
test('stale and missing requirements disable both question capture and refinement', () => {
  for (const current of [{ ...item, revision: 3 }, undefined]) {
    const html = render(current);
    for (const label of ['Track question', 'Track assumption', 'Review as a new revision'])
      assert.ok(html.includes(`<button disabled="">${label}</button>`), label);
  }
  assert.ok(!render(undefined).includes('Analyze current version'));
});
test('story reanalysis requires an in-scope signed-off current version and respects pending work', () => {
  for (const current of [{ ...item, revision: 3, status: 'draft' }, { ...item, revision: 3, priority: 'wont' }])
    assert.ok(render(current).includes('<button disabled="">Analyze current version</button>'));
  assert.ok(render({ ...item, revision: 3 }).includes('<button>Analyze current version</button>'));
  assert.ok(render({ ...item, revision: 3 }, 'review', true).includes('<button disabled="">Analyze current version</button>'));
});
