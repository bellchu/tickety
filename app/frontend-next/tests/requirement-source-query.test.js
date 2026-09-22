const assert = require('node:assert/strict');
const test = require('node:test');
const { QueryClient } = require('@tanstack/react-query');
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
