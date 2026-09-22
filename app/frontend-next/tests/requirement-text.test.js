const assert = require('node:assert/strict');
const test = require('node:test');
const { loadPureTs } = require('./helpers/load-pure-ts');
const { requirementTextBounds: bounds } = loadPureTs('requirement-text.ts');

test('source, passage and evidence bounds count code points and never shorten the input', () => {
  for (const limit of [4000, 12000, 100000]) {
    const text = '  ' + '𠮷'.repeat(limit) + '\n';
    assert.deepEqual(bounds(text, limit), { length: limit, valid: true });
    assert.deepEqual(bounds(text + 'x', limit), { length: limit + 2, valid: false });
    assert.equal(text.startsWith('  𠮷'), true);
  }
  assert.deepEqual(bounds('😀'.repeat(5), 4000), { length: 5, valid: false });
  assert.deepEqual(bounds('😀'.repeat(10), 4000), { length: 10, valid: true });
  assert.equal(bounds('A valid passage\0', 4000).valid, false);
  assert.deepEqual(bounds('   ', 4000), { length: 0, valid: false });
});
