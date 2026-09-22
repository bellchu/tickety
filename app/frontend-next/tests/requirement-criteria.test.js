const assert = require('node:assert/strict');
const test = require('node:test');
const { loadPureTs } = require('./helpers/load-pure-ts');
const parse = loadPureTs('requirement-criteria.ts', { './requirement-text': loadPureTs('requirement-text.ts') }).parseRequirementCriteria;

test('incomplete drafts may omit criteria and empty entries are ignored', () => {
  assert.deepEqual(parse([' ', '\r\n ']), { criteria: [], issue: null });
  assert.deepEqual(parse(['  Confirm receipt  ', '', '  Record time  ']), { criteria: ['Confirm receipt', 'Record time'], issue: null });
});
test('validation identifies the original criterion position after empty entries', () => {
  const invalid = parse(['Confirm receipt', '', ' short ']);
  assert.match(invalid.issue, /Criterion 3 has 5 characters/);
  assert.equal(invalid.invalidIndex, 2);
  assert.equal(parse(['Confirm receipt', '', 'Valid criterion']).invalidIndex, undefined);
  assert.equal(parse(['x'.repeat(10)]).issue, null);
  assert.equal(parse(['x'.repeat(1000)]).issue, null);
  assert.match(parse(['x'.repeat(1001)]).issue, /1001 characters/);
});
test('criterion count is bounded independently of total text length', () => {
  assert.equal(parse(Array(20).fill('Confirm receipt')).issue, null);
  assert.match(parse(Array(21).fill('Confirm receipt')).issue, /21 acceptance criteria/);
});
test('character limits use Unicode code points like the backend', () => {
  assert.match(parse(['😀'.repeat(5)]).issue, /5 characters/);
  assert.equal(parse(['😀'.repeat(1000)]).issue, null);
  assert.match(parse(['😀'.repeat(1001)]).issue, /1001 characters/);
});
test('saved and suggested multiline criteria retain their boundaries during editing', () => {
  const original = ['Given a valid request,\nwhen submitted,\nthen return a receipt.', 'If delivery fails,\nretain the request for retry.'];
  const result = parse(original);
  assert.deepEqual(result, { criteria: original, issue: null });
  const edited = [...original];
  edited[1] += '\nShow its reference to the operator.';
  assert.equal(parse(edited).criteria.length, 2);
  assert.equal(parse(edited).criteria[0], original[0]);
  assert.equal(original[1], 'If delivery fails,\nretain the request for retry.');
});

test('unsupported control characters are located before submitting criteria', () => {
  const result = parse(['Confirm the receipt.', 'Keep the\0request for retry.']);
  assert.match(result.issue, /Criterion 2.*unsupported control character/);
  assert.equal(result.invalidIndex, 1);
  assert.equal(result.criteria[1], 'Keep the\0request for retry.');
});
