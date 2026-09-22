const assert = require('node:assert/strict');
const test = require('node:test');
const { QueryClient } = require('@tanstack/react-query');
const { loadPureTs } = require('./helpers/load-pure-ts');
const { invalidateRequirementOverviews } = loadPureTs('requirement-workspace-query.ts');

test('saved work expires every overview page and search without refetching hidden lists', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: 15000 } } });
  let requests = 0;
  const options = [0, 25].flatMap(offset => ['', 'supplier'].map(search => ({
    queryKey: ['requirement-workspaces', offset, search],
    queryFn: async () => ({ stories: ++requests }),
  })));
  try {
    for (const option of options) await client.fetchQuery(option);
    client.setQueryData(['requirement-source', 'user', 'workspace', 'source'], { content: 'Immutable material' });
    await client.fetchQuery(options[0]);
    assert.equal(requests, 4, 'fresh cached overview is reused before a save');
    await invalidateRequirementOverviews(client);
    assert.equal(requests, 4, 'invalidation does not fetch hidden pages');
    for (const option of options) {
      assert.equal(client.getQueryState(option.queryKey).isInvalidated, true);
      await client.fetchQuery(option);
    }
    assert.equal(requests, 8, 'each overview fetch sees the saved work immediately');
    assert.equal(client.getQueryState(['requirement-source', 'user', 'workspace', 'source']).isInvalidated, false);
  } finally { client.clear(); }
});
