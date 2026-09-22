const assert = require('node:assert/strict');
const test = require('node:test');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { loadPureTs, loadComponentTs } = require('./helpers/load-pure-ts');
const dependencies = {
  'react/jsx-runtime': require('react/jsx-runtime'), './fields': { panelStyle: '' },
  '@/lib/requirement-review-question': loadPureTs('requirement-review-question.ts'),
  '@/lib/requirement-workspace': loadPureTs('requirement-workspace.ts'),
  '@/components/ui': { Button: ({ children, disabled }) => React.createElement('button', { disabled }, children) },
};
const { AIRequirementReview } = loadComponentTs('requirements/AIRequirementReview.tsx', dependencies);
const item = { id: 'r1', reference: 'REQ-001', revision: 2, status: 'validated', priority: 'must' };
function render(current, mode = 'story', busy = false) {
  return renderToStaticMarkup(React.createElement(AIRequirementReview, {
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


test('tracking a review finding preserves context, revision and affected requirement', () => {
  let tracked;
  const tree = AIRequirementReview({
    assistance: { item, result: { mode: 'review', model: 'Test', base_revision: 2,
      suggestions: { findings: [{ category: 'scope', finding: 'The retry owner is unclear.', question: 'Who owns retry handling?' }] } } },
    current: item, busy: false, onDismiss() {}, onReanalyze() {}, onRefine() {},
    onQuestion: (question, requirementId) => { tracked = { question, requirementId }; },
  });
  function find(node) {
    if (!node || typeof node !== 'object') return null;
    if (node.props?.children === 'Track question') return node;
    return React.Children.toArray(node.props?.children).map(find).find(Boolean);
  }
  const button = find(tree);
  assert.equal(button.props.disabled, false);
  button.props.onClick();
  assert.equal(tracked.requirementId, 'r1');
  assert.equal(tracked.question, 'AI review · REQ-001 r2\nQuestion: Who owns retry handling?\n\nContext to confirm: The retry owner is unclear.');
});
