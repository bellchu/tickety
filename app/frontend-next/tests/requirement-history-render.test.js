const assert = require('node:assert/strict');
const test = require('node:test');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { loadPureTs, loadComponentTs } = require('./helpers/load-pure-ts');
const before = { reference: 'REQ-001', source_id: 's1' };
const event = { id: 'history', revision: 2, action: 'edited', created_at: '2026-09-22', actor_id: 'reviewer', before, after: { ...before, source_id: 's2' } };
const { RequirementHistoryPanel } = loadComponentTs('requirements/RequirementHistoryPanel.tsx', {
  react: React, 'react/jsx-runtime': require('react/jsx-runtime'),
  '@tanstack/react-query': { useQuery: () => ({ data: { total: 1, items: [event] } }) },
  './fields': { priorities: {} },
  '@/lib/requirement-history': loadPureTs('requirement-history.ts'),
  '@/lib/requirement-errors': { requirementErrorMessage: String },
  '@/lib/api': { api: {} }, '@/lib/date-time': { formatLocalDateTime: String },
  '@/components/ui': { Button: ({ children }) => React.createElement('button', {}, children) },
});
const render = sources => renderToStaticMarkup(React.createElement(RequirementHistoryPanel, { workspaceId: 'w1', itemId: 'r1', revision: 2, sourceNames: new Map(sources), onClose() {} }));
test('source history uses readable titles while preserving distinct evidence identifiers', () => {
  const html = render([['s1', 'Operations SOP'], ['s2', 'Operations SOP']]);
  assert.ok(html.includes('Operations SOP (s1)'));
  assert.ok(html.includes('Operations SOP (s2)'));
  const missing = render([['s2', 'Updated interview']]);
  assert.ok(missing.includes('Source unavailable (s1)'));
  assert.ok(missing.includes('Updated interview (s2)'));
});
