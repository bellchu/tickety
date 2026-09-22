const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const ts = require('typescript');
const { QueryClient } = require('@tanstack/react-query');
const output = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../lib/requirement-editor-cache.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const loaded = { exports: {} };
new Function('exports', 'module', output)(loaded.exports, loaded);
const { readRequirementEditor: read, rememberRequirementEditor: remember, hasRequirementEditorDrafts: hasDrafts } = loaded.exports;
const draft = { draft: { title: 'Unsaved outcome' }, criteria: 'Confirm receipt', baseline: 'original', assumptions: ['Check deadline'], editing: { id: 'r1', revision: 7 }, showForm: true, reviewing: null, reviewerRole: 'Product Owner', reviewNote: '' };

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
  const { readRequirementSourceDraft: readSource, rememberRequirementSourceDraft: rememberSource } = loaded.exports;
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
  const { readRequirementDecisionDraft: readDecision, rememberRequirementDecisionDraft: rememberDecision } = loaded.exports;
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
