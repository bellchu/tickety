const assert = require('node:assert/strict');
const test = require('node:test');
const { QueryClient } = require('@tanstack/react-query');
const { loadPureTs } = require('./helpers/load-pure-ts');
const library = loadPureTs('requirement-editor-cache.ts');
const { readRequirementEditor: read, rememberRequirementEditor: remember, hasRequirementEditorDrafts: hasDrafts } = library;
const draft = { draft: { title: 'Unsaved outcome' }, criteria: ['Confirm receipt'], baseline: 'original', assumptions: ['Check deadline'], editing: { id: 'r1', revision: 7 }, showForm: true, reviewing: null, reviewerRole: 'Product Owner', reviewNote: '' };

test('navigation restores edits and original revision without crossing users or initiatives', () => {
  const client = new QueryClient();
  remember(client, 'alice', 'one', draft);
  assert.deepEqual(read(client, 'alice', 'one'), draft);
  assert.equal(read(client, 'bob', 'one'), undefined);
  assert.equal(read(client, 'alice', 'two'), undefined);
  assert.equal(client.getQueryCache().getAll()[0].gcTime, Infinity);
  assert.equal(hasDrafts(client), true);
  client.clear();
});
test('saving or discarding removes only that initiative draft', () => {
  const client = new QueryClient();
  remember(client, 'alice', 'one', draft);
  remember(client, 'alice', 'two', { ...draft, reviewNote: 'Unfinished review' });
  remember(client, 'alice', 'one', null);
  assert.equal(read(client, 'alice', 'one'), undefined);
  assert.equal(read(client, 'alice', 'two').reviewNote, 'Unfinished review');
  assert.equal(hasDrafts(client), true);
  remember(client, 'alice', 'two', null);
  assert.equal(hasDrafts(client), false);
  client.clear();
});
test('logout cache clearing removes drafts and the unload warning condition', () => {
  const client = new QueryClient();
  remember(client, 'alice', 'one', draft);
  client.clear();
  assert.equal(read(client, 'alice', 'one'), undefined);
  assert.equal(hasDrafts(client), false);
  client.setQueryData(['requirement-workspace', 'one'], { title: 'Saved content' });
  assert.equal(hasDrafts(client), false);
  client.clear();
});

test('source previews retain warnings independently of the requirement editor', () => {
  const client = new QueryClient();
  const { readRequirementSourceDraft: readSource, rememberRequirementSourceDraft: rememberSource } = library;
  const source = { title: 'Interview notes', kind: 'transcript', content: 'Confirm receipt within thirty seconds.', warnings: ['Images were omitted.'] };
  remember(client, 'alice', 'one', draft);
  rememberSource(client, 'alice', 'one', source);
  assert.deepEqual(readSource(client, 'alice', 'one'), source);
  assert.equal(readSource(client, 'bob', 'one'), undefined);
  assert.equal(readSource(client, 'alice', 'two'), undefined);
  remember(client, 'alice', 'one', null);
  assert.deepEqual(readSource(client, 'alice', 'one'), source);
  assert.equal(hasDrafts(client), true);
  rememberSource(client, 'alice', 'one', null);
  assert.equal(hasDrafts(client), false);
  rememberSource(client, 'alice', 'one', source);
  client.clear();
  assert.equal(readSource(client, 'alice', 'one'), undefined);
});

test('decision question and answer drafts coexist with source and editor drafts', () => {
  const client = new QueryClient();
  const { readRequirementDecisionDraft: readDecision, rememberRequirementDecisionDraft: rememberDecision } = library;
  const decision = { question: 'Who handles failures?', owner: 'Operations lead', requirementId: 'r1', blocking: false, resolving: 'q2', resolution: 'Keep failed submissions in the queue.' };
  remember(client, 'alice', 'one', draft);
  rememberDecision(client, 'alice', 'one', decision);
  assert.deepEqual(readDecision(client, 'alice', 'one'), decision);
  assert.equal(readDecision(client, 'bob', 'one'), undefined);
  assert.equal(readDecision(client, 'alice', 'two'), undefined);
  rememberDecision(client, 'alice', 'one', { ...decision, question: '', owner: '', requirementId: '', blocking: true });
  assert.equal(readDecision(client, 'alice', 'one').resolution, decision.resolution);
  rememberDecision(client, 'alice', 'one', null);
  assert.deepEqual(read(client, 'alice', 'one'), draft);
  rememberDecision(client, 'alice', 'one', decision);
  client.clear();
  assert.equal(readDecision(client, 'alice', 'one'), undefined);
});


test('late save completion cannot clear a newer draft after navigation', () => {
  const cases = [
    [undefined, library.rememberRequirementEditor, library.readRequirementEditor, draft, { ...draft, criteria: ['Newer acceptance wording'] }],
    ['source', library.rememberRequirementSourceDraft, library.readRequirementSourceDraft, { title: 'Original', content: 'Original material' }, { title: 'Newer', content: 'New material' }],
    ['decision', library.rememberRequirementDecisionDraft, library.readRequirementDecisionDraft, { question: 'Original question' }, { question: 'Newer question' }],
  ];
  for (const [kind, save, readDraft, original, newer] of cases) {
    const client = new QueryClient();
    save(client, 'alice', 'one', original);
    const isCurrent = library.captureRequirementDraftSave(client, 'alice', 'one', kind);
    assert.equal(isCurrent(), true);
    save(client, 'alice', 'one', newer);
    if (isCurrent()) save(client, 'alice', 'one', null);
    assert.deepEqual(readDraft(client, 'alice', 'one'), newer);
    const nextSave = library.captureRequirementDraftSave(client, 'alice', 'one', kind);
    assert.equal(nextSave(), true);
    client.clear();
    assert.equal(nextSave(), false);
  }
});

test('selected passages survive remounts without crossing material, initiative or account boundaries', () => {
  const client = new QueryClient();
  const read = library.readRequirementPassage;
  const remember = library.rememberRequirementPassage;
  remember(client, 'alice', 'w1', 's1', 'Exact passage from the first material.');
  remember(client, 'alice', 'w1', 's2', 'Different material passage.');
  assert.equal(read(client, 'alice', 'w1', 's1'), 'Exact passage from the first material.');
  assert.equal(read(client, 'bob', 'w1', 's1'), '');
  assert.equal(read(client, 'alice', 'w2', 's1'), '');
  assert.equal(hasDrafts(client), true);
  remember(client, 'alice', 'w1', 's1', '');
  assert.equal(read(client, 'alice', 'w1', 's1'), '');
  assert.equal(read(client, 'alice', 'w1', 's2'), 'Different material passage.');
  client.clear();
  assert.equal(read(client, 'alice', 'w1', 's2'), '');
  assert.equal(hasDrafts(client), false);
});
