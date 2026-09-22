const assert = require('node:assert/strict');
const test = require('node:test');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { loadPureTs, loadComponentTs } = require('./helpers/load-pure-ts');
const { RequirementCard } = loadComponentTs('requirements/RequirementCard.tsx', {
  'react/jsx-runtime': require('react/jsx-runtime'),
  './fields': { priorities: loadPureTs('requirement-workspace.ts').requirementPriorityLabels },
  'lucide-react': { CheckCircle2: () => null, Sparkles: () => null },
  '@/components/ui': { Button: ({ children, disabled }) => React.createElement('button', { disabled }, children) },
  '@/lib/date-time': { formatLocalDateTime: String },
});
const item = { id: 'r1', reference: 'REQ-001', title: 'Receipt', action: 'Confirm receipt', benefit: 'Track intake', actor: 'Analyst', priority: 'must', status: 'validated', quality_issues: [], evidence_quote: 'Confirm receipt.', acceptance_criteria: ['Current requirement criterion'], story: { reference: 'US-001', requirement_reference: 'REQ-001', validated_revision: 2, statement: 'As an analyst, I want a receipt.', acceptance_criteria: ['Delivery acceptance snapshot'] } };
const render = row => renderToStaticMarkup(React.createElement(RequirementCard, { item: row, sourceTitle: 'SOP', canAI: false, busy: false, pending: '', blocked: false }));
test('delivery card shows the story acceptance snapshot and its signed-off revision', () => {
  const html = render(item);
  assert.ok(html.includes('Acceptance criteria for delivery'));
  assert.ok(html.includes('Delivery acceptance snapshot'));
  assert.ok(html.includes('Signed-off revision 2'));
  assert.ok(html.includes('Copy story'));
});
test('deferred requirements retain evidence without presenting an old story for delivery', () => {
  const html = render({ ...item, priority: 'wont' });
  assert.ok(html.includes('Current requirement criterion'));
  assert.ok(!html.includes('Delivery acceptance snapshot'));
  assert.ok(!html.includes('Copy story'));
});
