const assert = require('node:assert/strict');
const test = require('node:test');
const { loadPureTs } = require('./helpers/load-pure-ts');
const { locateEvidenceQuote: locate } = loadPureTs('requirement-evidence.ts');

test('repeated quotations navigate exact positions including Unicode and overlapping matches', () => {
  const quote = '😀 Confirm receipt.';
  const content = `${quote}\nEarlier correspondence:\n${quote}`;
  const second = content.lastIndexOf(quote);
  assert.deepEqual(locate(content, quote), { position: 0, previous: -1, next: second });
  assert.deepEqual(locate(content, quote, second), { position: second, previous: 0, next: -1 });
  assert.equal(content.slice(second, second + quote.length), quote);
  assert.deepEqual(locate('aaaaa', 'aaa', 1), { position: 1, previous: 0, next: 2 });
});

test('unique, missing or changed quotations do not produce stale navigation targets', () => {
  assert.deepEqual(locate('A receipt is required.', 'receipt'), { position: 2, previous: -1, next: -1 });
  assert.deepEqual(locate('A receipt is required.', 'receipt', 8), { position: 2, previous: -1, next: -1 });
  assert.deepEqual(locate('Source text', ''), { position: -1, previous: -1, next: -1 });
  assert.deepEqual(locate('Source text', 'missing', 0), { position: -1, previous: -1, next: -1 });
});

test('source navigation moves the highlight while keeping the selected passage intact', () => {
  const React = require('react');
  const { loadComponentTs } = require('./helpers/load-pure-ts');
  const quote = 'Confirm receipt within 30 seconds.';
  const content = `${quote}\nPrevious message:\n${quote}`;
  const state = [];
  let cursor = 0;
  let passageWrites = 0;
  const { SourceExplorer } = loadComponentTs('requirements/SourceExplorer.tsx', {
    react: {
      useState: initial => { const index = cursor++; if (!(index in state)) state[index] = typeof initial === 'function' ? initial() : initial; return [state[index], next => { state[index] = next; }]; },
      useMemo: calculate => calculate(), useRef: () => ({ current: null }), useEffect() {},
    },
    'react/jsx-runtime': require('react/jsx-runtime'),
    '@tanstack/react-query': { useQueryClient: () => ({}) },
    '@/lib/requirement-evidence': { locateEvidenceQuote: locate },
    '@/lib/requirement-text': loadPureTs('requirement-text.ts'),
    '@/lib/requirement-editor-cache': { readRequirementPassage: () => quote, rememberRequirementPassage: () => { passageWrites++; } },
    'lucide-react': { Sparkles: 'span' }, '@/components/ui': { Button: 'button' }, './fields': { Field: 'label', inputStyle: '' },
  });
  function descendants(node, type) {
    if (!node || typeof node !== 'object') return [];
    return [...(node.type === type ? [node] : []), ...React.Children.toArray(node.props?.children).flatMap(child => descendants(child, type))];
  }
  let focus = { quote, reference: 'REQ-001' };
  const render = () => { cursor = 0; return SourceExplorer({ userId: 'u', workspaceId: 'w', sourceId: 's', content, focus, busy: false, canAI: false, onCapture() {}, onExplore: async () => {} }); };
  const button = (tree, label) => descendants(tree, 'button').find(node => node.props.children === label);
  const offset = tree => descendants(tree, 'pre')[0].props.children.props.children[0].length;
  let tree = render();
  assert.equal(offset(tree), 0);
  assert.equal(button(tree, 'Previous occurrence').props.disabled, true);
  button(tree, 'Next occurrence').props.onClick();
  tree = render();
  assert.equal(offset(tree), content.lastIndexOf(quote));
  const pieces = descendants(tree, 'pre')[0].props.children.props.children;
  assert.equal(pieces[0] + pieces[1].props.children + pieces[2], content);
  assert.equal(button(tree, 'Next occurrence').props.disabled, true);
  assert.equal(descendants(tree, 'textarea')[0].props.value, quote);
  button(tree, 'Previous occurrence').props.onClick();
  tree = render();
  assert.equal(offset(tree), 0);
  button(tree, 'Next occurrence').props.onClick();
  focus = { quote, reference: 'REQ-002' };
  tree = render();
  assert.equal(offset(tree), 0);
  assert.equal(descendants(tree, 'mark')[0].props['aria-label'], 'Evidence for REQ-002');
  assert.equal(passageWrites, 0);
});
