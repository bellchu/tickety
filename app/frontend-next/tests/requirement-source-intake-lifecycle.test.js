const assert = require('node:assert/strict');
const test = require('node:test');
const React = require('react');
const { QueryClient } = require('@tanstack/react-query');
const { loadPureTs, loadComponentTs } = require('./helpers/load-pure-ts');
const drafts = loadPureTs('requirement-editor-cache.ts');

function pendingImport(client) {
  let finish, fail;
  const request = new Promise((resolve, reject) => { finish = resolve; fail = reject; });
  const dependencies = {
    './BoundedText': loadComponentTs('requirements/BoundedText.tsx', {
      'react/jsx-runtime': require('react/jsx-runtime'), '@/lib/requirement-text': loadPureTs('requirement-text.ts'),
    }),
    react: { ...React, useEffect() {}, useMemo: compute => compute(), useState: initial => [typeof initial === 'function' ? initial() : initial, () => {}] },
    'react/jsx-runtime': require('react/jsx-runtime'),
    '@tanstack/react-query': { useQueryClient: () => client },
    '@/lib/requirement-text': loadPureTs('requirement-text.ts'),
    '@/lib/requirement-source-import': { prepareRequirementSource: () => request },
    '@/lib/requirement-errors': { requirementErrorMessage: String },
    '@/lib/requirement-editor-cache': drafts,
    '@/lib/api': { api: {} }, '@/components/ui': { Button: 'button', ConfirmDialog: () => null },
    './fields': { Field: 'label', inputStyle: '', panelStyle: '', kinds: {} },
  };
  const { SourceIntakeForm } = loadComponentTs('requirements/SourceIntakeForm.tsx', dependencies);
  const tree = SourceIntakeForm({ workspaceId: 'w1', userId: 'owner', open: true, pending: '', onSave() {} });
  function findInput(node) {
    if (!node || typeof node !== 'object') return undefined;
    if (node.type === 'input' && node.props.type === 'file') return node;
    return React.Children.toArray(node.props?.children).map(findInput).find(Boolean);
  }
  findInput(tree).props.onChange({ target: { files: [{}], value: 'source.pdf' } });
  return async result => { if (result instanceof Error) fail(result); else finish(result); await new Promise(setImmediate); };
}
const preview = { title: 'Imported interview', kind: 'document', content: 'A complete extracted interview.', warnings: ['Images omitted'] };
test('completed import survives navigation even when its component no longer renders', async () => {
  const client = new QueryClient();
  try {
    const finish = pendingImport(client);
    await finish(preview);
    assert.deepEqual(drafts.readRequirementSourceDraft(client, 'owner', 'w1'), preview);
    assert.equal(drafts.readRequirementSourceDraft(client, 'other', 'w1'), undefined);
  } finally { client.clear(); }
});
test('a late import cannot replace a newer source draft', async () => {
  const client = new QueryClient();
  try {
    const finish = pendingImport(client);
    const newer = { ...preview, title: 'Newer handwritten material' };
    drafts.rememberRequirementSourceDraft(client, 'owner', 'w1', newer);
    await finish(preview);
    assert.deepEqual(drafts.readRequirementSourceDraft(client, 'owner', 'w1'), newer);
  } finally { client.clear(); }
});

test('sign-out cache clearing prevents a late import from recreating the source draft', async () => {
  const client = new QueryClient();
  try {
    const finish = pendingImport(client);
    client.clear();
    await finish(preview);
    assert.equal(drafts.readRequirementSourceDraft(client, 'owner', 'w1'), undefined);
  } finally { client.clear(); }
});

test('failed imports restore the previous draft and remove an empty pending placeholder', async () => {
  for (const original of [undefined, preview]) {
    const client = new QueryClient();
    try {
      if (original) drafts.rememberRequirementSourceDraft(client, 'owner', 'w1', original);
      const finish = pendingImport(client);
      await finish(new Error('Unable to extract this document'));
      assert.deepEqual(drafts.readRequirementSourceDraft(client, 'owner', 'w1'), original);
    } finally { client.clear(); }
  }
});
