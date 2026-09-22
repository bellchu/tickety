const assert = require('node:assert/strict');
const test = require('node:test');
const { QueryClient, QueryObserver } = require('@tanstack/react-query');
const { loadPureTs } = require('./helpers/load-pure-ts');
const { requirementSourceQuery } = loadPureTs('requirement-source-query.ts');

test('immutable source content is reused within an account and loaded again across account boundaries', async () => {
  const client = new QueryClient();
  let requests = 0;
  const load = async (workspaceId, sourceId) => { requests++; return { id: sourceId, content: workspaceId + ' original evidence' }; };
  const options = requirementSourceQuery('alice', 'workspace', 'source', load);
  await client.fetchQuery(options);
  await client.fetchQuery(options);
  assert.equal(requests, 1);
  await client.fetchQuery(requirementSourceQuery('bob', 'workspace', 'source', load));
  assert.equal(requests, 2);
  client.clear();
  await client.fetchQuery(options);
  assert.equal(requests, 3);
  client.clear();
});


test('retrying a failed source read recovers the original text without clearing draft work', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { rememberRequirementEditor, readRequirementEditor } = loadPureTs('requirement-editor-cache.ts');
  const draft = { criteria: ['Given an outage,\nretain the request.'], reviewNote: 'Confirm retry ownership.' };
  rememberRequirementEditor(client, 'alice', 'workspace', draft);
  let requests = 0;
  const options = requirementSourceQuery('alice', 'workspace', 'source', async () => {
    if (++requests === 1) throw new Error('Temporary connection failure');
    return { id: 'source', content: 'Original source text retained for review.' };
  });
  const observer = new QueryObserver(client, options);
  const failed = await observer.refetch();
  assert.equal(failed.isError, true);
  const recovered = await observer.refetch();
  assert.equal(recovered.isSuccess, true);
  assert.equal(recovered.data.content, 'Original source text retained for review.');
  assert.deepEqual(readRequirementEditor(client, 'alice', 'workspace'), draft);
  await client.fetchQuery(options);
  assert.equal(requests, 2);
  observer.destroy();
  client.clear();
});
