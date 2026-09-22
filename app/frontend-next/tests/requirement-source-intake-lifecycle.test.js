const assert = require('node:assert/strict');
const test = require('node:test');
const React = require('react');
const { descendants } = require('./helpers/react-tree');
const { QueryClient } = require('@tanstack/react-query');
const { loadPureTs, loadComponentTs } = require('./helpers/load-pure-ts');
const drafts = loadPureTs('requirement-editor-cache.ts');

function intake(client) {
  const state = [];
  let cursor = 0, preparations = 0;
  let finish, fail;
  const request = new Promise((resolve, reject) => { finish = resolve; fail = reject; });
  const dependencies = {
    './BoundedText': loadComponentTs('requirements/BoundedText.tsx', {
      'react/jsx-runtime': require('react/jsx-runtime'), '@/lib/requirement-text': loadPureTs('requirement-text.ts'),
    }),
    react: { ...React, useEffect() {}, useMemo: compute => compute(), useState: initial => { const index = cursor++; if (!(index in state)) state[index] = typeof initial === 'function' ? initial() : initial; return [state[index], value => { state[index] = value; }]; } },
    'react/jsx-runtime': require('react/jsx-runtime'),
    '@tanstack/react-query': { useQueryClient: () => client },
    '@/lib/requirement-text': loadPureTs('requirement-text.ts'),
    '@/lib/requirement-source-import': { prepareRequirementSource: () => { preparations++; return request; } },
    '@/lib/requirement-errors': { requirementErrorMessage: String },
    '@/lib/requirement-editor-cache': drafts,
    '@/lib/api': { api: {} }, '@/components/ui': { Button: 'button', ConfirmDialog: 'dialog' },
    './fields': { Field: 'label', inputStyle: '', panelStyle: '', kinds: {} },
  };
  const { SourceIntakeForm } = loadComponentTs('requirements/SourceIntakeForm.tsx', dependencies);
  const render = () => { cursor = 0; return SourceIntakeForm({ workspaceId: 'w1', userId: 'owner', open: true, pending: '', onSave() {} }); };
  return {
    render,
    get preparations() { return preparations; },
    select() { descendants(render(), 'input').find(node => node.props.type === 'file').props.onChange({ target: { files: [{ name: 'source.pdf' }], value: 'source.pdf' } }); },
    replacement() { return descendants(render(), 'dialog').find(node => node.props.title === 'Replace unsaved source material?'); },
    async finish(result) { if (result instanceof Error) fail(result); else finish(result); await new Promise(setImmediate); },
  };
}
function pendingImport(client) {
  const form = intake(client);
  form.select();
  if (form.replacement().props.open) form.replacement().props.onConfirm();
  return form.finish;
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


test('replacing unsaved source material waits for confirmation and cancellation keeps the draft', async () => {
  const client = new QueryClient();
  const original = { ...preview, title: 'Manually reviewed interview' };
  try {
    drafts.rememberRequirementSourceDraft(client, 'owner', 'w1', original);
    const form = intake(client);
    form.select();
    assert.equal(form.replacement().props.open, true);
    assert.equal(form.preparations, 0, 'no file extraction or upload before the choice');
    form.replacement().props.onOpenChange(false);
    assert.equal(form.replacement().props.open, false);
    assert.deepEqual(drafts.readRequirementSourceDraft(client, 'owner', 'w1'), original);
    assert.equal(descendants(form.render(), 'textarea')[0].props.value, original.content);
    form.select();
    form.replacement().props.onConfirm();
    assert.equal(form.preparations, 1);
    assert.equal(form.replacement().props.open, false);
    await form.finish(preview);
    assert.deepEqual(drafts.readRequirementSourceDraft(client, 'owner', 'w1'), preview);
    assert.equal(descendants(form.render(), 'textarea')[0].props.value, preview.content);
  } finally { client.clear(); }
});
