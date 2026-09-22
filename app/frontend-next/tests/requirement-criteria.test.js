const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const ts = require('typescript');
const output = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../lib/requirement-criteria.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const loaded = { exports: {} };
new Function('exports', 'module', output)(loaded.exports, loaded);
const parse = loaded.exports.parseRequirementCriteria;
test('incomplete drafts may omit criteria; blank lines are not entries', () => {
  assert.deepEqual(parse(' \n\r\n '), { criteria: [], issue: null });
  assert.deepEqual(parse('  Confirm receipt  \r\n\n  Record time  '), { criteria: ['Confirm receipt', 'Record time'], issue: null });
});
test('per-line validation identifies the original line after blank lines', () => {
  assert.match(parse('Confirm receipt\n\n short ').issue, /Line 3 has 5 characters/);
  assert.equal(parse('x'.repeat(10)).issue, null);
  assert.equal(parse('x'.repeat(1000)).issue, null);
  assert.match(parse('x'.repeat(1001)).issue, /1001 characters/);
});
test('criterion count is bounded independently of total text length', () => {
  assert.equal(parse(Array(20).fill('Confirm receipt').join('\n')).issue, null);
  assert.match(parse(Array(21).fill('Confirm receipt').join('\n')).issue, /21 acceptance criteria/);
});
test('character limits use Unicode code points like the backend', () => {
  assert.match(parse('😀'.repeat(5)).issue, /5 characters/);
  assert.equal(parse('😀'.repeat(1000)).issue, null);
  assert.match(parse('😀'.repeat(1001)).issue, /1001 characters/);
});
