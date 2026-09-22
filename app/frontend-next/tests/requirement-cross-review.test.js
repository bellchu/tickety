const { descendants } = require('./helpers/react-tree');
const assert = require('node:assert/strict');
const test = require('node:test');
const { loadComponentTs, loadPureTs } = require('./helpers/load-pure-ts');


test('cross-check keeps selected scope visible and submits it across changing searches', async () => {
  const states = [];
  let cursor = 0;
  let submitted;
  let tracked;
  let scans = 0;
  const workspace = loadPureTs('requirement-workspace.ts');
  const { CrossReviewPanel } = loadComponentTs('requirements/CrossReviewPanel.tsx', {
    react: { useMemo: calculate => calculate(), useState: initial => {
      const index = cursor++;
      if (!(index in states)) states[index] = initial;
      return [states[index], value => { states[index] = value; }];
    } },
    'react/jsx-runtime': require('react/jsx-runtime'),
    '@/components/ui': { Button: 'button' },
    './fields': { Field: 'div', inputStyle: '' },
    '@/lib/requirement-review-question': loadPureTs('requirement-review-question.ts'),
    '@/lib/requirement-workspace': { ...workspace, filterRequirements(...args) { scans++; return workspace.filterRequirements(...args); } },
    '@/lib/requirement-errors': { requirementErrorMessage: error => error.message },
    '@/lib/api': { api: { crossReviewRequirements: async (workspaceId, ids) => {
      submitted = { workspaceId, ids };
      return { requirements: [{ id: '0', reference: 'REQ-001', revision: 1 }], findings: [{ references: ['REQ-001'], category: 'scope_gap', finding: 'The retry owner is unclear.', question: 'Who owns retry handling?' }], model: 'test' };
    } } },
  });
  const items = ['Receipt', 'Retry'].map((title, index) => ({ id: String(index), reference: `REQ-00${index + 1}`, title, revision: 1, quality_issues: [], acceptance_criteria: [], story: null }));
  const render = () => { cursor = 0; return CrossReviewPanel({ workspaceId: 'workspace', items, onQuestion: (question, requirementId) => { tracked = { question, requirementId }; } }); };
  const search = (tree, value) => descendants(tree, 'input').find(input => input.props.type === 'search').props.onChange({ target: { value } });
  const checkboxes = tree => descendants(tree, 'input').filter(input => input.props.type === 'checkbox');
  const closed = render();
  assert.equal(scans, 0, 'closed cross-check does not scan requirement text');
  descendants(closed, 'button')[0].props.onClick();
  let tree = render();
  checkboxes(tree)[0].props.onChange({ target: { checked: true } });
  tree = render();
  search(tree, 'Retry');
  tree = render();
  assert.equal(checkboxes(tree).length, 1);
  assert.ok(descendants(tree, 'button').some(button => button.props['aria-label'] === 'Remove REQ-001 from cross-check'));
  checkboxes(tree)[0].props.onChange({ target: { checked: true } });
  tree = render();
  search(tree, 'unmatched');
  tree = render();
  assert.equal(checkboxes(tree).length, 0);
  descendants(tree, 'button').find(button => button.props.children === 'Close cross-check').props.onClick();
  const scansBeforeClose = scans;
  tree = render();
  render();
  assert.equal(scans, scansBeforeClose, 'hidden search remains idle through parent renders');
  descendants(tree, 'button')[0].props.onClick();
  tree = render();
  assert.equal(checkboxes(tree).length, 0, 'reopening retains the search');
  const review = descendants(tree, 'button').find(button => button.props.children === 'Review selected requirements');
  assert.equal(review.props.disabled, false);
  await review.props.onClick();
  assert.deepEqual(submitted, { workspaceId: 'workspace', ids: ['0', '1'] });
  tree = render();
  const track = descendants(tree, 'button').find(button => button.props.children === 'Track review question');
  assert.equal(track.props.disabled, false);
  track.props.onClick();
  assert.equal(tracked.requirementId, '0');
  assert.equal(tracked.question, 'AI review · REQ-001 r1\nQuestion: Who owns retry handling?\n\nContext to confirm: The retry owner is unclear.');
  descendants(tree, 'button').find(button => button.props['aria-label'] === 'Remove REQ-001 from cross-check').props.onClick();
  tree = render();
  assert.equal(descendants(tree, 'button').find(button => button.props.children === 'Review selected requirements').props.disabled, true);
});
